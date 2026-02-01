"""
Trigger Workflow Lambda
Manually triggers Step Functions workflow for incidents
Can be called from API, CLI, or other services
"""

import json
import boto3
from datetime import datetime
from typing import Dict, Optional

dynamodb = boto3.resource('dynamodb')
stepfunctions = boto3.client('stepfunctions')

incidents_table = dynamodb.Table('ITOps-Incidents')

class WorkflowTrigger:
    """Handles workflow triggering and management"""
    
    def __init__(self):
        self.trigger_id = 'workflow-trigger'
        self.state_machine_arn = 'arn:aws:states:us-east-1:005185643085:stateMachine:ITOps-IncidentWorkflow'
    
    def trigger_workflow(
        self,
        incident_id: str = None,
        incident_data: Dict = None,
        execution_name: str = None
    ) -> Dict:
        """
        Trigger Step Functions workflow
        
        Args:
            incident_id: Existing incident ID or None for new
            incident_data: Incident data (required if incident_id not provided)
            execution_name: Custom execution name (optional)
        
        Returns:
            Workflow trigger result
        """
        
        # Case 1: Existing incident - fetch from DynamoDB
        if incident_id and not incident_data:
            incident_data = self._get_incident(incident_id)
            if not incident_data:
                return {
                    'success': False,
                    'error': f'Incident {incident_id} not found'
                }
        
        # Case 2: New incident - create it
        elif not incident_id and incident_data:
            incident_id = self._create_incident(incident_data)
            incident_data['incident_id'] = incident_id
        
        # Case 3: Both provided - use as-is
        elif incident_id and incident_data:
            # Ensure incident_id matches
            incident_data['incident_id'] = incident_id
        
        # Case 4: Neither provided - error
        else:
            return {
                'success': False,
                'error': 'Must provide either incident_id or incident_data'
            }
        
        # Generate execution name
        if not execution_name:
            timestamp = int(datetime.now().timestamp())
            execution_name = f"{incident_id}_{timestamp}"
        
        # Start Step Functions execution
        try:
            response = stepfunctions.start_execution(
                stateMachineArn=self.state_machine_arn,
                name=execution_name,
                input=json.dumps({
                    'incident_id': incident_id,
                    'incident': incident_data
                })
            )
            
            execution_arn = response['executionArn']
            
            # Update incident with workflow info
            self._update_incident_workflow(incident_id, execution_arn)
            
            return {
                'success': True,
                'incident_id': incident_id,
                'execution_arn': execution_arn,
                'execution_name': execution_name,
                'state_machine': self.state_machine_arn,
                'started_at': response['startDate'].isoformat(),
                'message': 'Workflow started successfully',
                'console_url': self._get_console_url(execution_arn)
            }
        
        except stepfunctions.exceptions.ExecutionAlreadyExists:
            return {
                'success': False,
                'error': f'Execution {execution_name} already exists',
                'suggestion': 'Use a different execution name or wait for current execution to complete'
            }
        
        except Exception as e:
            return {
                'success': False,
                'error': f'Failed to start workflow: {str(e)}'
            }
    
    def retry_workflow(self, incident_id: str) -> Dict:
        """
        Retry workflow for failed incident
        
        Args:
            incident_id: Incident to retry
        
        Returns:
            Retry result
        """
        
        incident_data = self._get_incident(incident_id)
        if not incident_data:
            return {
                'success': False,
                'error': f'Incident {incident_id} not found'
            }
        
        # Generate new execution name with retry suffix
        timestamp = int(datetime.now().timestamp())
        execution_name = f"{incident_id}_retry_{timestamp}"
        
        return self.trigger_workflow(
            incident_id=incident_id,
            incident_data=incident_data,
            execution_name=execution_name
        )
    
    def trigger_batch(self, incident_ids: list) -> Dict:
        """
        Trigger workflows for multiple incidents
        
        Args:
            incident_ids: List of incident IDs
        
        Returns:
            Batch trigger results
        """
        
        results = {
            'total': len(incident_ids),
            'succeeded': [],
            'failed': []
        }
        
        for incident_id in incident_ids:
            result = self.trigger_workflow(incident_id=incident_id)
            
            if result.get('success'):
                results['succeeded'].append({
                    'incident_id': incident_id,
                    'execution_arn': result.get('execution_arn')
                })
            else:
                results['failed'].append({
                    'incident_id': incident_id,
                    'error': result.get('error')
                })
        
        return results
    
    def get_execution_status(self, execution_arn: str) -> Dict:
        """
        Get current status of workflow execution
        
        Args:
            execution_arn: Step Functions execution ARN
        
        Returns:
            Execution status details
        """
        
        try:
            response = stepfunctions.describe_execution(
                executionArn=execution_arn
            )
            
            return {
                'success': True,
                'execution_arn': execution_arn,
                'status': response['status'],
                'started_at': response['startDate'].isoformat(),
                'stopped_at': response.get('stopDate', '').isoformat() if response.get('stopDate') else None,
                'input': json.loads(response['input']),
                'output': json.loads(response.get('output', '{}')) if response.get('output') else None
            }
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def stop_execution(self, execution_arn: str, reason: str = None) -> Dict:
        """
        Stop running workflow execution
        
        Args:
            execution_arn: Execution to stop
            reason: Optional stop reason
        
        Returns:
            Stop result
        """
        
        try:
            stepfunctions.stop_execution(
                executionArn=execution_arn,
                error='ManualStop',
                cause=reason or 'Manually stopped via trigger-workflow'
            )
            
            return {
                'success': True,
                'execution_arn': execution_arn,
                'message': 'Execution stopped',
                'reason': reason
            }
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def _get_incident(self, incident_id: str) -> Optional[Dict]:
        """Get incident from DynamoDB"""
        
        try:
            response = incidents_table.query(
                KeyConditionExpression='incident_id = :id',
                ExpressionAttributeValues={':id': incident_id}
            )
            
            items = response.get('Items', [])
            return items[0] if items else None
        
        except Exception as e:
            print(f"Error getting incident: {e}")
            return None
    
    def _create_incident(self, incident_data: Dict) -> str:
        """Create new incident in DynamoDB"""
        
        timestamp = int(datetime.now().timestamp())
        incident_id = incident_data.get('incident_id') or f"INC-{timestamp}"
        
        incident = {
            'incident_id': incident_id,
            'created_at': timestamp,
            'title': incident_data.get('title', 'Untitled Incident'),
            'description': incident_data.get('description', ''),
            'severity': incident_data.get('severity', 'medium'),
            'status': 'open',
            'affected_services': incident_data.get('affected_services', []),
            'detected_by': incident_data.get('detected_by', 'manual'),
            'timeline': []
        }
        
        try:
            incidents_table.put_item(Item=incident)
            print(f"Created incident: {incident_id}")
            return incident_id
        
        except Exception as e:
            print(f"Error creating incident: {e}")
            raise
    
    def _update_incident_workflow(self, incident_id: str, execution_arn: str):
        """Update incident with workflow execution info"""
        
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
                        SET workflow_execution_arn = :arn,
                            workflow_started_at = :timestamp,
                            timeline = list_append(if_not_exists(timeline, :empty_list), :event)
                    ''',
                    ExpressionAttributeValues={
                        ':arn': execution_arn,
                        ':timestamp': int(datetime.now().timestamp()),
                        ':empty_list': [],
                        ':event': [{
                            'timestamp': int(datetime.now().timestamp()),
                            'event': 'workflow_started',
                            'actor': 'workflow_trigger',
                            'details': f'Execution ARN: {execution_arn}'
                        }]
                    }
                )
        
        except Exception as e:
            print(f"Error updating incident: {e}")
    
    def _get_console_url(self, execution_arn: str) -> str:
        """Generate AWS Console URL for execution"""
        
        return f"https://console.aws.amazon.com/states/home?region=us-east-1#/executions/details/{execution_arn}"


def lambda_handler(event, context):
    """
    Lambda handler for workflow triggering
    
    Event formats:
    
    1. Trigger for existing incident:
    {
        "action": "trigger",
        "incident_id": "INC-XXXXX"
    }
    
    2. Trigger with new incident:
    {
        "action": "trigger",
        "incident": {
            "title": "...",
            "description": "...",
            "severity": "high",
            "affected_services": [...]
        }
    }
    
    3. Retry failed incident:
    {
        "action": "retry",
        "incident_id": "INC-XXXXX"
    }
    
    4. Trigger batch:
    {
        "action": "batch",
        "incident_ids": ["INC-001", "INC-002"]
    }
    
    5. Get execution status:
    {
        "action": "status",
        "execution_arn": "arn:..."
    }
    
    6. Stop execution:
    {
        "action": "stop",
        "execution_arn": "arn:...",
        "reason": "Manual stop"
    }
    """
    
    print(f"Workflow Trigger received: {json.dumps(event)}")
    
    trigger = WorkflowTrigger()
    
    try:
        action = event.get('action', 'trigger')
        
        if action == 'trigger':
            incident_id = event.get('incident_id')
            incident_data = event.get('incident')
            execution_name = event.get('execution_name')
            
            result = trigger.trigger_workflow(
                incident_id=incident_id,
                incident_data=incident_data,
                execution_name=execution_name
            )
            
            return {
                'statusCode': 200 if result.get('success') else 400,
                'body': json.dumps(result)
            }
        
        elif action == 'retry':
            incident_id = event.get('incident_id')
            
            if not incident_id:
                return {
                    'statusCode': 400,
                    'body': json.dumps({
                        'success': False,
                        'error': 'Missing incident_id'
                    })
                }
            
            result = trigger.retry_workflow(incident_id)
            
            return {
                'statusCode': 200 if result.get('success') else 400,
                'body': json.dumps(result)
            }
        
        elif action == 'batch':
            incident_ids = event.get('incident_ids', [])
            
            if not incident_ids:
                return {
                    'statusCode': 400,
                    'body': json.dumps({
                        'success': False,
                        'error': 'Missing incident_ids'
                    })
                }
            
            result = trigger.trigger_batch(incident_ids)
            
            return {
                'statusCode': 200,
                'body': json.dumps(result)
            }
        
        elif action == 'status':
            execution_arn = event.get('execution_arn')
            
            if not execution_arn:
                return {
                    'statusCode': 400,
                    'body': json.dumps({
                        'success': False,
                        'error': 'Missing execution_arn'
                    })
                }
            
            result = trigger.get_execution_status(execution_arn)
            
            return {
                'statusCode': 200 if result.get('success') else 400,
                'body': json.dumps(result)
            }
        
        elif action == 'stop':
            execution_arn = event.get('execution_arn')
            reason = event.get('reason')
            
            if not execution_arn:
                return {
                    'statusCode': 400,
                    'body': json.dumps({
                        'success': False,
                        'error': 'Missing execution_arn'
                    })
                }
            
            result = trigger.stop_execution(execution_arn, reason)
            
            return {
                'statusCode': 200 if result.get('success') else 400,
                'body': json.dumps(result)
            }
        
        else:
            return {
                'statusCode': 400,
                'body': json.dumps({
                    'success': False,
                    'error': f'Invalid action: {action}',
                    'valid_actions': ['trigger', 'retry', 'batch', 'status', 'stop']
                })
            }
    
    except Exception as e:
        print(f"Error in workflow trigger: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'error': str(e)
            })
        }