"""
Approval Checker
Checks if a remediation plan has been approved
"""

import json
import boto3

dynamodb = boto3.resource('dynamodb')
approval_queue = dynamodb.Table('ITOps-ApprovalQueue')

def lambda_handler(event, context):
    """Check approval status"""
    
    print(f"Checking approval for: {json.dumps(event)}")
    
    try:
        approval_id = event.get('approval_id')
        
        if not approval_id:
            return {
                'statusCode': 400,
                'approved': False,
                'error': 'No approval_id provided'
            }
        
        # Get approval record
        response = approval_queue.query(
            KeyConditionExpression='approval_id = :id',
            ExpressionAttributeValues={':id': approval_id}
        )
        
        items = response.get('Items', [])
        
        if not items:
            return {
                'statusCode': 404,
                'approved': False,
                'status': 'not_found'
            }
        
        approval = items[0]
        status = approval.get('status', 'pending')
        
        return {
            'statusCode': 200,
            'approved': status == 'approved',
            'status': status,
            'approval_id': approval_id,
            'comments': approval.get('comments', '')
        }
    
    except Exception as e:
        print(f"Error: {e}")
        return {
            'statusCode': 500,
            'approved': False,
            'error': str(e)
        }