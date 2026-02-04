"""
API Handler for Incident Management
Handles HTTP requests from API Gateway
"""

import json
import boto3
from datetime import datetime

lambda_client = boto3.client('lambda')
stepfunctions = boto3.client('stepfunctions')
dynamodb = boto3.resource('dynamodb')

incidents_table = dynamodb.Table('ITOps-Incidents')
approval_queue = dynamodb.Table('ITOps-ApprovalQueue')

def lambda_handler(event, context):
    """
    Main API handler
    Routes requests based on HTTP method and path
    """
    
    print(f"API Request: {json.dumps(event)}")
    
    # CORS headers
    headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type'
    }
    
    try:
        http_method = event.get('httpMethod')
        path = event.get('path', '')
        
        # Handle OPTIONS for CORS
        if http_method == 'OPTIONS':
            return {
                'statusCode': 200,
                'headers': headers,
                'body': ''
            }
        
        # Parse path
        if path.startswith('/incidents'):
            if http_method == 'GET':
                if '/' in path[11:]:  # /incidents/{id}
                    incident_id = path.split('/')[-1]
                    response = get_incident(incident_id)
                else:  # /incidents
                    query_params = event.get('queryStringParameters', {}) or {}
                    response = list_incidents(query_params)
            
            elif http_method == 'POST':
                body = json.loads(event.get('body', '{}'))
                response = create_incident(body)
            
            elif http_method == 'PUT':
                incident_id = path.split('/')[-1]
                body = json.loads(event.get('body', '{}'))
                response = update_incident(incident_id, body)
            
            elif http_method == 'DELETE':
                incident_id = path.split('/')[-1]
                response = delete_incident(incident_id)
            
            else:
                response = {'statusCode': 405, 'body': {'error': 'Method not allowed'}}
        
        elif path.startswith('/workflow'):
            body = json.loads(event.get('body', '{}'))
            response = start_workflow(body)
        
        elif path.startswith('/approvals'):
            if http_method == 'GET':
                response = list_approvals()
            elif http_method == 'PUT':
                approval_id = path.split('/')[-1]
                body = json.loads(event.get('body', '{}'))
                response = update_approval(approval_id, body)
            else:
                response = {'statusCode': 405, 'body': {'error': 'Method not allowed'}}
        
        else:
            response = {'statusCode': 404, 'body': {'error': 'Not found'}}
        
        return {
            'statusCode': response.get('statusCode', 200),
            'headers': headers,
            'body': json.dumps(response.get('body', response))
        }
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'headers': headers,
            'body': json.dumps({'error': str(e)})
        }

def create_incident(data):
    """Create new incident and start workflow"""
    
    # Call MCP Incident server
    response = lambda_client.invoke(
        FunctionName='ITOps-MCP-Incident',
        InvocationType='RequestResponse',
        Payload=json.dumps({
            'action': 'execute',
            'tool_name': 'create_incident',
            'parameters': data
        })
    )
    
    result = json.loads(response['Payload'].read())
    
    if result.get('statusCode') != 200:
        return {'statusCode': 500, 'body': result}
    
    incident = result['result']['incident']
    
    # Start workflow
    workflow_response = lambda_client.invoke(
        FunctionName='ITOps-Workflow-Init',
        InvocationType='Event',  # Async
        Payload=json.dumps({
            'incident_id': incident['incident_id'],
            'incident': incident
        })
    )
    
    return {
        'statusCode': 201,
        'body': {
            'incident': incident,
            'workflow_started': True
        }
    }

def get_incident(incident_id):
    """Get incident by ID"""
    
    response = incidents_table.query(
        KeyConditionExpression='incident_id = :id',
        ExpressionAttributeValues={':id': incident_id}
    )
    
    items = response.get('Items', [])
    
    if not items:
        return {'statusCode': 404, 'body': {'error': 'Incident not found'}}
    
    return {'statusCode': 200, 'body': items[0]}

def list_incidents(query_params):
    """List incidents with optional filters"""
    
    status = query_params.get('status')
    limit = int(query_params.get('limit', '50'))
    
    if status:
        response = incidents_table.query(
            IndexName='status-index',
            KeyConditionExpression='#status = :status',
            ExpressionAttributeNames={'#status': 'status'},
            ExpressionAttributeValues={':status': status},
            Limit=limit,
            ScanIndexForward=False
        )
    else:
        response = incidents_table.scan(Limit=limit)
    
    items = response.get('Items', [])
    
    return {
        'statusCode': 200,
        'body': {
            'incidents': items,
            'count': len(items)
        }
    }

def update_incident(incident_id, data):
    """Update incident"""
    
    # Get current incident
    response = incidents_table.query(
        KeyConditionExpression='incident_id = :id',
        ExpressionAttributeValues={':id': incident_id}
    )
    
    if not response.get('Items'):
        return {'statusCode': 404, 'body': {'error': 'Incident not found'}}
    
    created_at = response['Items'][0]['created_at']
    
    # Build update expression
    update_expr = []
    expr_values = {}
    expr_names = {}
    
    for key, value in data.items():
        if key not in ['incident_id', 'created_at']:
            update_expr.append(f"#{key} = :{key}")
            expr_values[f":{key}"] = value
            expr_names[f"#{key}"] = key
    
    if not update_expr:
        return {'statusCode': 400, 'body': {'error': 'No valid fields to update'}}
    
    incidents_table.update_item(
        Key={'incident_id': incident_id, 'created_at': created_at},
        UpdateExpression='SET ' + ', '.join(update_expr),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values
    )
    
    return {'statusCode': 200, 'body': {'message': 'Incident updated', 'incident_id': incident_id}}

def delete_incident(incident_id):
    """Delete incident"""
    
    response = incidents_table.query(
        KeyConditionExpression='incident_id = :id',
        ExpressionAttributeValues={':id': incident_id}
    )
    
    if not response.get('Items'):
        return {'statusCode': 404, 'body': {'error': 'Incident not found'}}
    
    created_at = response['Items'][0]['created_at']
    
    incidents_table.delete_item(
        Key={'incident_id': incident_id, 'created_at': created_at}
    )
    
    return {'statusCode': 200, 'body': {'message': 'Incident deleted', 'incident_id': incident_id}}

def start_workflow(data):
    """Start workflow for existing incident"""
    
    incident_id = data.get('incident_id')
    
    if not incident_id:
        return {'statusCode': 400, 'body': {'error': 'incident_id required'}}
    
    response = lambda_client.invoke(
        FunctionName='ITOps-Workflow-Init',
        InvocationType='RequestResponse',
        Payload=json.dumps(data)
    )
    
    result = json.loads(response['Payload'].read())
    
    return {'statusCode': 200, 'body': json.loads(result.get('body', '{}'))}

def list_approvals():
    """List pending approvals"""
    
    response = approval_queue.scan(
        FilterExpression='#status = :status',
        ExpressionAttributeNames={'#status': 'status'},
        ExpressionAttributeValues={':status': 'pending'}
    )
    
    return {
        'statusCode': 200,
        'body': {
            'approvals': response.get('Items', []),
            'count': len(response.get('Items', []))
        }
    }

def update_approval(approval_id, data):
    """Approve or reject remediation"""
    
    status = data.get('status')  # 'approved' or 'rejected'
    comments = data.get('comments', '')
    
    if status not in ['approved', 'rejected']:
        return {'statusCode': 400, 'body': {'error': 'Invalid status'}}
    
    response = approval_queue.query(
        KeyConditionExpression='approval_id = :id',
        ExpressionAttributeValues={':id': approval_id}
    )
    
    if not response.get('Items'):
        return {'statusCode': 404, 'body': {'error': 'Approval not found'}}
    
    created_at = response['Items'][0]['created_at']
    
    approval_queue.update_item(
        Key={'approval_id': approval_id, 'created_at': created_at},
        UpdateExpression='SET #status = :status, comments = :comments, updated_at = :updated',
        ExpressionAttributeNames={'#status': 'status'},
        ExpressionAttributeValues={
            ':status': status,
            ':comments': comments,
            ':updated': int(datetime.now().timestamp())
        }
    )
    
    return {
        'statusCode': 200,
        'body': {
            'message': f'Approval {status}',
            'approval_id': approval_id
        }
    }