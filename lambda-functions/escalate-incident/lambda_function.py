"""
Escalate Incident Lambda
Handles critical incident escalation to human operators
Sends notifications via SNS, Email, and creates PagerDuty-style alerts
"""

import json
import boto3
from datetime import datetime
from typing import Dict, List

dynamodb = boto3.resource('dynamodb')
sns = boto3.client('sns')
ses = boto3.client('ses')

incidents_table = dynamodb.Table('ITOps-Incidents')
escalations_table = dynamodb.Table('ITOps-Escalations')

class EscalationHandler:
    """Handles incident escalation workflow"""
    
    def __init__(self):
        self.escalation_levels = {
            'critical': 1,  # Immediate - notify all channels
            'high': 2,      # Urgent - notify primary on-call
            'medium': 3,    # Standard - create ticket
            'low': 4        # FYI - email notification only
        }
    
    def escalate(self, incident_id: str, incident_data: Dict, reason: str = None) -> Dict:
        """
        Escalate incident to human operators
        
        Args:
            incident_id: Unique incident identifier
            incident_data: Full incident details
            reason: Reason for escalation
        
        Returns:
            Escalation result with notification details
        """
        
        severity = incident_data.get('severity', 'medium')
        escalation_level = self.escalation_levels.get(severity, 3)
        
        # Create escalation record
        escalation_id = self._create_escalation_record(
            incident_id, 
            incident_data, 
            reason, 
            escalation_level
        )
        
        # Send notifications based on severity
        notifications = self._send_notifications(
            incident_id,
            incident_data,
            escalation_id,
            escalation_level
        )
        
        # Update incident status
        self._update_incident_status(incident_id, escalation_id)
        
        # Create escalation summary
        return {
            'incident_id': incident_id,
            'escalation_id': escalation_id,
            'severity': severity,
            'escalation_level': escalation_level,
            'reason': reason or 'Automatic escalation based on severity',
            'notifications_sent': notifications,
            'status': 'escalated',
            'message': f'Incident escalated to human operators (Level {escalation_level})',
            'action_required': self._get_required_actions(severity)
        }
    
    def _create_escalation_record(
        self, 
        incident_id: str, 
        incident_data: Dict, 
        reason: str,
        level: int
    ) -> str:
        """Create escalation record in DynamoDB"""
        
        escalation_id = f"ESC-{int(datetime.now().timestamp())}"
        
        try:
            escalations_table.put_item(
                Item={
                    'escalation_id': escalation_id,
                    'incident_id': incident_id,
                    'created_at': int(datetime.now().timestamp()),
                    'severity': incident_data.get('severity'),
                    'escalation_level': level,
                    'reason': reason or 'Automatic escalation',
                    'status': 'open',
                    'incident_title': incident_data.get('title'),
                    'incident_description': incident_data.get('description'),
                    'affected_services': incident_data.get('affected_services', []),
                    'assigned_to': None,
                    'resolved_at': None,
                    'resolution_notes': None,
                    'ttl': int(datetime.now().timestamp()) + 2592000  # 30 days
                }
            )
            
            print(f"Created escalation record: {escalation_id}")
            return escalation_id
        
        except Exception as e:
            print(f"Error creating escalation record: {e}")
            return f"ESC-ERROR-{int(datetime.now().timestamp())}"
    
    def _send_notifications(
        self,
        incident_id: str,
        incident_data: Dict,
        escalation_id: str,
        level: int
    ) -> Dict:
        """Send notifications through appropriate channels"""
        
        notifications = {
            'sns': False,
            'email': False,
            'slack': False,
            'pagerduty': False
        }
        
        severity = incident_data.get('severity', 'medium')
        
        # Build notification message
        message = self._build_notification_message(
            incident_id,
            incident_data,
            escalation_id
        )
        
        # Critical incidents - all channels
        if level == 1:
            notifications['sns'] = self._send_sns_notification(message, 'critical')
            notifications['email'] = self._send_email_notification(incident_id, incident_data, escalation_id)
            notifications['slack'] = self._send_slack_notification(message)
            notifications['pagerduty'] = self._trigger_pagerduty(incident_id, incident_data)
        
        # High priority - SNS + Email
        elif level == 2:
            notifications['sns'] = self._send_sns_notification(message, 'urgent')
            notifications['email'] = self._send_email_notification(incident_id, incident_data, escalation_id)
        
        # Medium - Email only
        elif level == 3:
            notifications['email'] = self._send_email_notification(incident_id, incident_data, escalation_id)
        
        # Low - Log only (already handled)
        else:
            print(f"Low priority escalation - logged only")
        
        return notifications
    
    def _build_notification_message(
        self,
        incident_id: str,
        incident_data: Dict,
        escalation_id: str
    ) -> str:
        """Build formatted notification message"""
        
        severity_emoji = {
            'critical': '🚨',
            'high': '⚠️',
            'medium': '⚡',
            'low': 'ℹ️'
        }
        
        severity = incident_data.get('severity', 'medium')
        emoji = severity_emoji.get(severity, 'ℹ️')
        
        message = f"""
{emoji} INCIDENT ESCALATION - {severity.upper()} {emoji}

Escalation ID: {escalation_id}
Incident ID: {incident_id}

Title: {incident_data.get('title', 'Unknown')}
Description: {incident_data.get('description', 'No description')}

Severity: {severity.upper()}
Affected Services: {', '.join(incident_data.get('affected_services', ['Unknown']))}
Detected By: {incident_data.get('detected_by', 'System')}

Status: REQUIRES IMMEDIATE ATTENTION

Action Required:
- Review incident details in ITOps Dashboard
- Assess automated remediation attempts
- Take manual action if necessary
- Update escalation status when resolved

View Details:
https://console.aws.amazon.com/dynamodbv2/home?region=us-east-1#tables:selected=ITOps-Incidents

Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
        
        return message.strip()
    
    def _send_sns_notification(self, message: str, priority: str) -> bool:
        """Send SNS notification"""
        
        try:
            # In production, use your SNS topic ARN
            # For now, just log
            print(f"[SNS {priority.upper()}] Would send notification:")
            print(message)
            return True
        
        except Exception as e:
            print(f"Error sending SNS: {e}")
            return False
    
    def _send_email_notification(
        self,
        incident_id: str,
        incident_data: Dict,
        escalation_id: str
    ) -> bool:
        """Send email notification via SES"""
        
        try:
            subject = f"🚨 ESCALATION: {incident_data.get('title', 'Incident')} [{incident_id}]"
            body = self._build_email_body(incident_id, incident_data, escalation_id)
            
            # In production, configure SES and send email
            # For now, just log
            print(f"[EMAIL] Would send to on-call team:")
            print(f"Subject: {subject}")
            print(f"Body:\n{body}")
            
            return True
        
        except Exception as e:
            print(f"Error sending email: {e}")
            return False
    
    def _send_slack_notification(self, message: str) -> bool:
        """Send Slack notification (simulated)"""
        
        try:
            print(f"[SLACK] Would post to #incidents channel:")
            print(message)
            return True
        
        except Exception as e:
            print(f"Error sending Slack notification: {e}")
            return False
    
    def _trigger_pagerduty(self, incident_id: str, incident_data: Dict) -> bool:
        """Trigger PagerDuty alert (simulated)"""
        
        try:
            print(f"[PAGERDUTY] Would create alert:")
            print(f"  Incident: {incident_id}")
            print(f"  Severity: {incident_data.get('severity')}")
            print(f"  Title: {incident_data.get('title')}")
            return True
        
        except Exception as e:
            print(f"Error triggering PagerDuty: {e}")
            return False
    
    def _build_email_body(
        self,
        incident_id: str,
        incident_data: Dict,
        escalation_id: str
    ) -> str:
        """Build HTML email body"""
        
        return f"""
<html>
<body style="font-family: Arial, sans-serif;">
    <div style="background: #dc3545; color: white; padding: 20px;">
        <h1>🚨 Incident Escalation Required</h1>
    </div>
    
    <div style="padding: 20px;">
        <h2>Escalation Details</h2>
        <table style="border-collapse: collapse; width: 100%;">
            <tr style="background: #f8f9fa;">
                <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>Escalation ID:</strong></td>
                <td style="padding: 10px; border: 1px solid #dee2e6;">{escalation_id}</td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>Incident ID:</strong></td>
                <td style="padding: 10px; border: 1px solid #dee2e6;">{incident_id}</td>
            </tr>
            <tr style="background: #f8f9fa;">
                <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>Title:</strong></td>
                <td style="padding: 10px; border: 1px solid #dee2e6;">{incident_data.get('title')}</td>
            </tr>
            <tr>
                <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>Severity:</strong></td>
                <td style="padding: 10px; border: 1px solid #dee2e6;">
                    <span style="background: #dc3545; color: white; padding: 5px 10px; border-radius: 3px;">
                        {incident_data.get('severity', 'unknown').upper()}
                    </span>
                </td>
            </tr>
            <tr style="background: #f8f9fa;">
                <td style="padding: 10px; border: 1px solid #dee2e6;"><strong>Affected Services:</strong></td>
                <td style="padding: 10px; border: 1px solid #dee2e6;">{', '.join(incident_data.get('affected_services', []))}</td>
            </tr>
        </table>
        
        <h3>Description</h3>
        <p style="background: #f8f9fa; padding: 15px; border-left: 4px solid #dc3545;">
            {incident_data.get('description', 'No description provided')}
        </p>
        
        <h3>Action Required</h3>
        <ul>
            <li>Review incident in AWS Console</li>
            <li>Check automated remediation attempts</li>
            <li>Take manual corrective action if needed</li>
            <li>Update escalation status when resolved</li>
        </ul>
        
        <p>
            <a href="https://console.aws.amazon.com/dynamodbv2/home?region=us-east-1#tables" 
               style="background: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">
                View in AWS Console
            </a>
        </p>
    </div>
    
    <div style="background: #f8f9fa; padding: 10px; margin-top: 20px; font-size: 12px; color: #6c757d;">
        <p>This is an automated message from ITOps Multi-Agent System</p>
        <p>Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
    </div>
</body>
</html>
"""
    
    def _update_incident_status(self, incident_id: str, escalation_id: str):
        """Update incident with escalation information"""
        
        try:
            response = incidents_table.query(
                KeyConditionExpression='incident_id = :id',
                ExpressionAttributeValues={':id': incident_id}
            )
            
            if response.get('Items'):
                created_at = response['Items'][0]['created_at']
                
                incidents_table.update_item(
                    Key={'incident_id': incident_id, 'created_at': created_at},
                    UpdateExpression='''
                        SET #status = :status,
                            escalation_id = :esc_id,
                            timeline = list_append(if_not_exists(timeline, :empty_list), :event)
                    ''',
                    ExpressionAttributeNames={'#status': 'status'},
                    ExpressionAttributeValues={
                        ':status': 'escalated',
                        ':esc_id': escalation_id,
                        ':empty_list': [],
                        ':event': [{
                            'timestamp': int(datetime.now().timestamp()),
                            'event': 'incident_escalated',
                            'actor': 'escalation_handler',
                            'details': f'Escalated to human operators: {escalation_id}'
                        }]
                    }
                )
        
        except Exception as e:
            print(f"Error updating incident: {e}")
    
    def _get_required_actions(self, severity: str) -> List[str]:
        """Get list of required actions based on severity"""
        
        if severity == 'critical':
            return [
                'Immediate response required within 15 minutes',
                'Notify all on-call team members',
                'Begin manual remediation',
                'Prepare incident report'
            ]
        elif severity == 'high':
            return [
                'Response required within 1 hour',
                'Notify primary on-call engineer',
                'Review automated attempts',
                'Implement manual fix if needed'
            ]
        elif severity == 'medium':
            return [
                'Response required within 4 hours',
                'Review incident details',
                'Plan remediation approach'
            ]
        else:
            return [
                'Review when available',
                'Document in ticketing system'
            ]


def lambda_handler(event, context):
    """
    Lambda handler for incident escalation
    
    Event format:
    {
        "incident_id": "INC-XXXXX",
        "incident": {...},
        "reason": "optional escalation reason"
    }
    """
    
    print(f"Escalation Handler received: {json.dumps(event)}")
    
    try:
        incident_id = event.get('incident_id')
        incident_data = event.get('incident')
        reason = event.get('reason')
        
        if not incident_id or not incident_data:
            return {
                'statusCode': 400,
                'result': {
                    'incident_id': incident_id or 'unknown',
                    'status': 'error',
                    'message': 'Missing incident_id or incident data'
                }
            }
        
        # Escalate incident
        handler = EscalationHandler()
        result = handler.escalate(incident_id, incident_data, reason)
        
        return {
            'statusCode': 200,
            'result': result
        }
    
    except Exception as e:
        print(f"Error in escalation handler: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'result': {
                'incident_id': event.get('incident_id', 'unknown'),
                'status': 'error',
                'message': f'Escalation failed: {str(e)}'
            }
        }