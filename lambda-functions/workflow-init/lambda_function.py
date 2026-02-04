"""
Workflow Initiator
Prepares incident data and starts the Step Functions workflow
"""

import json
import boto3
from datetime import datetime

stepfunctions = boto3.client('stepfunctions')
dynamodb = boto3.resource('dynamodb')

incidents_table = dynamodb.Table('ITOps-Incidents')

def lambda_handler(event, context):
    """
    Initiates incident response workflow
    
    Event can be:
    1. New incident from API Gateway
    2. Existing incident ID to reprocess
    """
    
    print(f"Workflow Initiator received: {json.dumps(event)}")
    
    try:
        # Check if this is a new incident or existing
        incident_id = event.get('incident_id')
        
        if incident_id:
            # Fetch existing incident
            response = incidents_table.query(
                KeyConditionExpression='incident_id = :id',
                ExpressionAttributeValues={':id': incident_id}
            )
            
            if not response.get('Items'):
                return {
                    'statusCode': 404,
                    'body': json.dumps({'error': 'Incident not found'})
                }
            
            incident_data = response['Items'][0]
        
        else:
            # Create new incident
            incident_id = event.get('incident', {}).get('incident_id')
            incident_data = event.get('incident', {})
            
            if not incident_data:
                return {
                    'statusCode': 400,
                    'body': json.dumps({'error': 'No incident data provided'})
                }
        
        # Start Step Functions execution
        state_machine_arn = f"arn:aws:states:{context.invoked_function_arn.split(':')[3]}:{context.invoked_function_arn.split(':')[4]}:stateMachine:ITOps-IncidentWorkflow"
        
        execution_response = stepfunctions.start_execution(
            stateMachineArn=state_machine_arn,
            name=f"{incident_id}_{int(datetime.now().timestamp())}",
            input=json.dumps({
                'incident_id': incident_id,
                'incident': incident_data
            })
        )
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Workflow started successfully',
                'incident_id': incident_id,
                'execution_arn': execution_response['executionArn']
            })
        }
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }