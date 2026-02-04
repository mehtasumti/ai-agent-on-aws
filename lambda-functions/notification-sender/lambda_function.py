"""
Notification Sender
Sends notifications about incident status
"""

import json
import boto3
from datetime import datetime

sns = boto3.client('sns')
dynamodb = boto3.resource('dynamodb')

incidents_table = dynamodb.Table('ITOps-Incidents')

def lambda_handler(event, context):
    """Send notification"""
    
    print(f"Sending notification: {json.dumps(event)}")
    
    try:
        incident_id = event.get('incident_id')
        notification_type = event.get('type', 'update')
        message_data = event.get('data', {})
        
        # Build notification message
        if notification_type == 'triage_complete':
            subject = f"Incident {incident_id} Triaged"
            message = f"""
Incident Triage Complete:
- Incident: {incident_id}
- Severity: {message_data.get('severity')}
- Routing: {message_data.get('routing')}
- Reasoning: {message_data.get('reasoning')}
"""
        
        elif notification_type == 'root_cause_found':
            subject = f"Root Cause Found: {incident_id}"
            message = f"""
Root Cause Analysis Complete:
- Incident: {incident_id}
- Root Cause: {message_data.get('root_cause')}
- Confidence: {message_data.get('confidence')}
"""
        
        elif notification_type == 'approval_required':
            subject = f"⚠️ Approval Required: {incident_id}"
            message = f"""
High-Risk Remediation Requires Approval:
- Incident: {incident_id}
- Risk Level: {message_data.get('risk_level')}
- Approval ID: {message_data.get('approval_id')}

Please review and approve/reject in the portal.
"""
        
        elif notification_type == 'resolved':
            subject = f"✅ Incident Resolved: {incident_id}"
            message = f"""
Incident Successfully Resolved:
- Incident: {incident_id}
- Actions Taken: {message_data.get('actions_count', 0)}
- Status: {message_data.get('status')}
"""
        
        else:
            subject = f"Incident Update: {incident_id}"
            message = json.dumps(message_data, indent=2)
        
        # Log notification (in production, would send via SNS/email)
        print(f"NOTIFICATION:\nSubject: {subject}\n{message}")
        
        # Update incident timeline
        if incident_id:
            response = incidents_table.query(
                KeyConditionExpression='incident_id = :id',
                ExpressionAttributeValues={':id': incident_id}
            )
            
            if response.get('Items'):
                created_at = response['Items'][0]['created_at']
                
                incidents_table.update_item(
                    Key={'incident_id': incident_id, 'created_at': created_at},
                    UpdateExpression='SET timeline = list_append(timeline, :event)',
                    ExpressionAttributeValues={
                        ':event': [{
                            'timestamp': int(datetime.now().timestamp()),
                            'event': f'notification_{notification_type}',
                            'actor': 'system',
                            'details': subject
                        }]
                    }
                )
        
        return {
            'statusCode': 200,
            'message': 'Notification sent successfully',
            'type': notification_type
        }
    
    except Exception as e:
        print(f"Error: {e}")
        return {
            'statusCode': 500,
            'error': str(e)
        }