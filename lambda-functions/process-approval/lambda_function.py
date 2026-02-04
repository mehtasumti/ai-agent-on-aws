"""
Process Approval Lambda
Handles approval/rejection of remediation plans
Provides API for approval workflow management
"""

import json
import boto3
from datetime import datetime
from typing import Dict, Optional

dynamodb = boto3.resource('dynamodb')
stepfunctions = boto3.client('stepfunctions')
sns = boto3.client('sns')

approval_queue_table = dynamodb.Table('ITOps-ApprovalQueue')
incidents_table = dynamodb.Table('ITOps-Incidents')

class ApprovalProcessor:
    """Handles approval workflow processing"""
    
    def __init__(self):
        self.processor_id = 'approval-processor'
    
    def process_approval(
        self,
        approval_id: str,
        action: str,
        approver: str,
        comments: str = None
    ) -> Dict:
        """
        Process approval decision
        
        Args:
            approval_id: Unique approval identifier
            action: 'approve' or 'reject'
            approver: Name/ID of approver
            comments: Optional approval comments
        
        Returns:
            Approval processing result
        """
        
        # Validate action
        if action not in ['approve', 'reject']:
            return {
                'success': False,
                'message': f"Invalid action: {action}. Must be 'approve' or 'reject'"
            }
        
        # Get approval record
        approval = self._get_approval(approval_id)
        if not approval:
            return {
                'success': False,
                'message': f"Approval {approval_id} not found"
            }
        
        # Check if already processed
        current_status = approval.get('status', 'pending')
        if current_status != 'pending':
            return {
                'success': False,
                'message': f"Approval already processed (status: {current_status})"
            }
        
        # Update approval status
        new_status = 'approved' if action == 'approve' else 'rejected'
        updated = self._update_approval_status(
            approval_id,
            new_status,
            approver,
            comments
        )
        
        if not updated:
            return {
                'success': False,
                'message': 'Failed to update approval status'
            }
        
        # Get incident details
        incident_id = approval.get('incident_id')
        
        # Send notification
        self._send_notification(
            approval_id,
            incident_id,
            new_status,
            approver,
            comments
        )
        
        # Update incident timeline
        self._update_incident_timeline(
            incident_id,
            approval_id,
            new_status,
            approver
        )
        
        # If approved, trigger execution
        if action == 'approve':
            execution_result = self._trigger_execution(approval, incident_id)
            
            return {
                'success': True,
                'approval_id': approval_id,
                'incident_id': incident_id,
                'status': new_status,
                'approver': approver,
                'message': 'Approval granted - remediation execution started',
                'execution': execution_result
            }
        else:
            return {
                'success': True,
                'approval_id': approval_id,
                'incident_id': incident_id,
                'status': new_status,
                'approver': approver,
                'message': 'Approval rejected - remediation will not be executed'
            }
    
    def get_approval_details(self, approval_id: str) -> Optional[Dict]:
        """Get full approval details"""
        
        approval = self._get_approval(approval_id)
        if not approval:
            return None
        
        return {
            'approval_id': approval_id,
            'incident_id': approval.get('incident_id'),
            'status': approval.get('status', 'pending'),
            'risk_level': approval.get('risk_level'),
            'created_at': approval.get('created_at'),
            'requested_by': approval.get('requested_by'),
            'plan': approval.get('plan'),
            'approver': approval.get('approver'),
            'approved_at': approval.get('approved_at'),
            'comments': approval.get('comments')
        }
    
    def list_pending_approvals(self, limit: int = 50) -> Dict:
        """List all pending approvals"""
        
        try:
            response = approval_queue_table.scan(
                FilterExpression='#status = :status',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':status': 'pending'},
                Limit=limit
            )
            
            approvals = response.get('Items', [])
            
            # Sort by created_at (newest first)
            approvals.sort(key=lambda x: x.get('created_at', 0), reverse=True)
            
            return {
                'success': True,
                'count': len(approvals),
                'approvals': approvals
            }
        
        except Exception as e:
            print(f"Error listing approvals: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def _get_approval(self, approval_id: str) -> Optional[Dict]:
        """Get approval record from DynamoDB"""
        
        try:
            response = approval_queue_table.query(
                KeyConditionExpression='approval_id = :id',
                ExpressionAttributeValues={':id': approval_id}
            )
            
            items = response.get('Items', [])
            return items[0] if items else None
        
        except Exception as e:
            print(f"Error getting approval: {e}")
            return None
    
    def _update_approval_status(
        self,
        approval_id: str,
        status: str,
        approver: str,
        comments: str = None
    ) -> bool:
        """Update approval status in DynamoDB"""
        
        try:
            update_expression = '''
                SET #status = :status,
                    approver = :approver,
                    approved_at = :timestamp
            '''
            expression_values = {
                ':status': status,
                ':approver': approver,
                ':timestamp': int(datetime.now().timestamp())
            }
            
            if comments:
                update_expression += ', comments = :comments'
                expression_values[':comments'] = comments
            
            approval_queue_table.update_item(
                Key={'approval_id': approval_id, 'created_at': self._get_created_at(approval_id)},
                UpdateExpression=update_expression,
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues=expression_values
            )
            
            print(f"Updated approval {approval_id} to {status}")
            return True
        
        except Exception as e:
            print(f"Error updating approval status: {e}")
            return False
    
    def _get_created_at(self, approval_id: str) -> int:
        """Get created_at timestamp for approval (sort key)"""
        
        approval = self._get_approval(approval_id)
        return approval.get('created_at', 0) if approval else 0
    
    def _send_notification(
        self,
        approval_id: str,
        incident_id: str,
        status: str,
        approver: str,
        comments: str = None
    ):
        """Send notification about approval decision"""
        
        status_emoji = '✅' if status == 'approved' else '❌'
        
        message = f"""
{status_emoji} APPROVAL {status.upper()} {status_emoji}

Approval ID: {approval_id}
Incident ID: {incident_id}
Decision: {status.upper()}
Approver: {approver}
Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
        
        if comments:
            message += f"\nComments: {comments}"
        
        if status == 'approved':
            message += "\n\nRemediation execution has been initiated."
        else:
            message += "\n\nRemediation will not be executed. Incident requires alternative approach."
        
        print(f"[NOTIFICATION] Would send approval notification:")
        print(message)
        
        # In production, send via SNS
        # sns.publish(TopicArn='...', Message=message, Subject=f'Approval {status}')
    
    def _update_incident_timeline(
        self,
        incident_id: str,
        approval_id: str,
        status: str,
        approver: str
    ):
        """Update incident timeline with approval decision"""
        
        try:
            response = incidents_table.query(
                KeyConditionExpression='incident_id = :id',
                ExpressionAttributeValues={':id': incident_id}
            )
            
            if response.get('Items'):
                created_at = response['Items'][0]['created_at']
                
                incidents_table.update_item(
                    Key={'incident_id': incident_id, 'created_at': created_at},
                    UpdateExpression='SET timeline = list_append(if_not_exists(timeline, :empty_list), :event)',
                    ExpressionAttributeValues={
                        ':empty_list': [],
                        ':event': [{
                            'timestamp': int(datetime.now().timestamp()),
                            'event': f'approval_{status}',
                            'actor': approver,
                            'details': json.dumps({
                                'approval_id': approval_id,
                                'status': status,
                                'approver': approver
                            })
                        }]
                    }
                )
        
        except Exception as e:
            print(f"Error updating incident timeline: {e}")
    
    def _trigger_execution(self, approval: Dict, incident_id: str) -> Dict:
        """Trigger remediation execution after approval"""
        
        try:
            plan = approval.get('plan', {})
            
            # In production, invoke execute-remediation Lambda
            # For now, simulate
            print(f"[EXECUTION] Would trigger remediation execution:")
            print(f"  Incident: {incident_id}")
            print(f"  Plan: {json.dumps(plan, indent=2)}")
            
            return {
                'triggered': True,
                'simulated': True,
                'message': 'Execution triggered (simulated)'
            }
        
        except Exception as e:
            print(f"Error triggering execution: {e}")
            return {
                'triggered': False,
                'error': str(e)
            }


def lambda_handler(event, context):
    """
    Lambda handler for approval processing
    
    Event formats:
    
    1. Process approval:
    {
        "action": "process",
        "approval_id": "APPR-XXXXX",
        "decision": "approve|reject",
        "approver": "john.doe",
        "comments": "optional comments"
    }
    
    2. Get approval details:
    {
        "action": "get",
        "approval_id": "APPR-XXXXX"
    }
    
    3. List pending approvals:
    {
        "action": "list",
        "limit": 50
    }
    
    4. API Gateway proxy format (for web UI):
    {
        "httpMethod": "POST|GET",
        "path": "/approvals",
        "body": "...",
        "queryStringParameters": {...}
    }
    """
    
    print(f"Approval Processor received: {json.dumps(event)}")
    
    processor = ApprovalProcessor()
    
    try:
        # Handle API Gateway proxy format
        if 'httpMethod' in event:
            return handle_api_request(event, processor)
        
        # Handle direct invocation
        action = event.get('action')
        
        if action == 'process':
            approval_id = event.get('approval_id')
            decision = event.get('decision')
            approver = event.get('approver', 'unknown')
            comments = event.get('comments')
            
            if not approval_id or not decision:
                return {
                    'statusCode': 400,
                    'body': json.dumps({
                        'success': False,
                        'message': 'Missing approval_id or decision'
                    })
                }
            
            result = processor.process_approval(approval_id, decision, approver, comments)
            
            return {
                'statusCode': 200 if result['success'] else 400,
                'body': json.dumps(result)
            }
        
        elif action == 'get':
            approval_id = event.get('approval_id')
            
            if not approval_id:
                return {
                    'statusCode': 400,
                    'body': json.dumps({
                        'success': False,
                        'message': 'Missing approval_id'
                    })
                }
            
            details = processor.get_approval_details(approval_id)
            
            if not details:
                return {
                    'statusCode': 404,
                    'body': json.dumps({
                        'success': False,
                        'message': 'Approval not found'
                    })
                }
            
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'success': True,
                    'approval': details
                })
            }
        
        elif action == 'list':
            limit = event.get('limit', 50)
            result = processor.list_pending_approvals(limit)
            
            return {
                'statusCode': 200,
                'body': json.dumps(result)
            }
        
        else:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'message': f"Invalid action: {action}"
                })
            }
    
    except Exception as e:
        print(f"Error in approval processor: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'error': str(e)
            })
        }


def handle_api_request(event: Dict, processor: ApprovalProcessor) -> Dict:
    """Handle API Gateway proxy requests"""
    
    method = event.get('httpMethod')
    path = event.get('path', '')
    
    # CORS headers
    headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET,POST,PUT,OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type'
    }
    
    # Handle OPTIONS (CORS preflight)
    if method == 'OPTIONS':
        return {
            'statusCode': 200,
            'headers': headers,
            'body': ''
        }
    
    # POST /approvals/{approval_id}/approve or /reject
    if method == 'POST' and '/approve' in path or '/reject' in path:
        approval_id = path.split('/')[2] if len(path.split('/')) > 2 else None
        decision = 'approve' if '/approve' in path else 'reject'
        
        body = json.loads(event.get('body', '{}'))
        approver = body.get('approver', 'api-user')
        comments = body.get('comments')
        
        result = processor.process_approval(approval_id, decision, approver, comments)
        
        return {
            'statusCode': 200 if result['success'] else 400,
            'headers': headers,
            'body': json.dumps(result)
        }
    
    # GET /approvals (list)
    elif method == 'GET' and path == '/approvals':
        params = event.get('queryStringParameters') or {}
        limit = int(params.get('limit', 50))
        
        result = processor.list_pending_approvals(limit)
        
        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps(result)
        }
    
    # GET /approvals/{approval_id} (get details)
    elif method == 'GET' and path.startswith('/approvals/'):
        approval_id = path.split('/')[2]
        details = processor.get_approval_details(approval_id)
        
        if not details:
            return {
                'statusCode': 404,
                'headers': headers,
                'body': json.dumps({'error': 'Not found'})
            }
        
        return {
            'statusCode': 200,
            'headers': headers,
            'body': json.dumps({'approval': details})
        }
    
    else:
        return {
            'statusCode': 404,
            'headers': headers,
            'body': json.dumps({'error': 'Not found'})
        }