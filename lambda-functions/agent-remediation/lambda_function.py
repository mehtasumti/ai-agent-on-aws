"""
Remediation Agent
Proposes and executes safe remediation actions
"""

import json
import boto3
from datetime import datetime
from typing import Dict, List

bedrock_runtime = boto3.client('bedrock-runtime')
dynamodb = boto3.resource('dynamodb')

agent_state_table = dynamodb.Table('ITOps-AgentState')
incidents_table = dynamodb.Table('ITOps-Incidents')
approval_queue_table = dynamodb.Table('ITOps-ApprovalQueue')
kb_table = dynamodb.Table('ITOps-KnowledgeBase')

class RemediationAgent:
    """
    AI Agent for generating and executing remediation plans
    """
    
    def __init__(self):
        self.agent_id = 'remediation-agent'
        self.model_id = 'anthropic.claude-3-5-sonnet-20241022-v2:0'
    
    def remediate(self, incident_id: str, incident_data: Dict, root_cause: Dict) -> Dict:
        """
        Generate and propose remediation plan
        
        Args:
            incident_id: Incident ID
            incident_data: Incident details
            root_cause: Root cause analysis results
        
        Returns:
            Remediation plan with actions
        """
        
        # Generate remediation plan
        plan = self._generate_plan(incident_data, root_cause)
        
        # Classify risk level
        risk_level = self._assess_risk(plan)
        
        # Determine if approval needed
        if risk_level in ['high', 'critical']:
            # Queue for human approval
            approval_id = self._queue_for_approval(incident_id, plan, risk_level)
            
            return {
                'incident_id': incident_id,
                'status': 'pending_approval',
                'approval_id': approval_id,
                'risk_level': risk_level,
                'plan': plan,
                'message': 'Remediation plan requires human approval due to risk level'
            }
        
        else:
            # Auto-execute safe remediations
            execution_result = self._execute_plan(incident_id, plan)
            
            # Update incident
            self._update_incident(incident_id, plan, execution_result)
            
            return {
                'incident_id': incident_id,
                'status': 'executed',
                'risk_level': risk_level,
                'plan': plan,
                'execution_result': execution_result
            }
    
    def _generate_plan(self, incident: Dict, root_cause: Dict) -> Dict:
        """Generate remediation plan using Claude"""
        
        prompt = f"""Generate a detailed remediation plan for this incident.

**Incident:**
- Title: {incident.get('title')}
- Description: {incident.get('description')}
- Severity: {incident.get('severity')}
- Affected Services: {', '.join(incident.get('affected_services', []))}

**Root Cause Analysis:**
{json.dumps(root_cause, indent=2)}

**Your Task:**
Create a remediation plan with:
1. Immediate actions (stop the bleeding)
2. Corrective actions (fix the root cause)
3. Preventive measures (avoid recurrence)

Provide plan in this JSON format:
{{
  "immediate_actions": [
    {{
      "action": "Action description",
      "command": "AWS CLI command or API call",
      "risk": "low|medium|high",
      "reversible": true|false
    }}
  ],
  "corrective_actions": [...],
  "preventive_measures": [...],
  "estimated_duration": "time estimate",
  "success_criteria": ["Criterion 1", "Criterion 2"]
}}

Be specific with actual AWS commands when possible."""

        response = self._call_bedrock(prompt)
        return self._parse_plan(response)
    
    def _assess_risk(self, plan: Dict) -> str:
        """Assess overall risk level of remediation plan"""
        
        all_actions = (
            plan.get('immediate_actions', []) +
            plan.get('corrective_actions', [])
        )
        
        risk_levels = [action.get('risk', 'medium') for action in all_actions]
        
        if 'high' in risk_levels or any(not action.get('reversible', True) for action in all_actions):
            return 'high'
        elif 'medium' in risk_levels:
            return 'medium'
        else:
            return 'low'
    
    def _queue_for_approval(self, incident_id: str, plan: Dict, risk_level: str) -> str:
        """Queue remediation for human approval"""
        
        import uuid
        approval_id = f"APPR-{uuid.uuid4().hex[:8].upper()}"
        
        try:
            approval_queue_table.put_item(
                Item={
                    'approval_id': approval_id,
                    'created_at': int(datetime.now().timestamp()),
                    'incident_id': incident_id,
                    'status': 'pending',
                    'risk_level': risk_level,
                    'plan': plan,
                    'requested_by': self.agent_id,
                    'ttl': int(datetime.now().timestamp()) + 86400  # 24 hours
                }
            )
            
            return approval_id
        
        except Exception as e:
            print(f"Error queuing approval: {e}")
            return None
    
    def _execute_plan(self, incident_id: str, plan: Dict) -> Dict:
        """Execute low-risk remediation actions"""
        
        results = []
        
        # Execute immediate actions
        for action in plan.get('immediate_actions', []):
            if action.get('risk') == 'low':
                result = self._execute_action(action)
                results.append(result)
        
        # Execute corrective actions
        for action in plan.get('corrective_actions', []):
            if action.get('risk') == 'low':
                result = self._execute_action(action)
                results.append(result)
        
        return {
            'executed_actions': len(results),
            'results': results,
            'status': 'completed' if all(r.get('success') for r in results) else 'partial'
        }
    
    def _execute_action(self, action: Dict) -> Dict:
        """Execute a single remediation action"""
        
        # In a real system, this would execute actual AWS commands
        # For this lab, we'll simulate execution
        
        print(f"Executing action: {action.get('action')}")
        print(f"Command: {action.get('command')}")
        
        return {
            'action': action.get('action'),
            'success': True,
            'simulated': True,
            'message': 'Action simulated successfully (would execute in production)'
        }
    
    def _parse_plan(self, response: str) -> Dict:
        """Parse remediation plan JSON"""
        try:
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end > 0:
                return json.loads(response[start:end])
        except Exception as e:
            print(f"Error parsing plan: {e}")
        
        # Fallback plan
        return {
            'immediate_actions': [{
                'action': 'Manual intervention required',
                'command': 'N/A',
                'risk': 'high',
                'reversible': False
            }],
            'corrective_actions': [],
            'preventive_measures': ['Review incident for patterns'],
            'estimated_duration': 'Unknown',
            'success_criteria': ['Issue resolved']
        }
    
    def _call_bedrock(self, prompt: str) -> str:
        """Call Bedrock API"""
        try:
            response = bedrock_runtime.invoke_model(
                modelId=self.model_id,
                body=json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 2000,
                    "temperature": 0.4,
                    "messages": [{"role": "user", "content": prompt}]
                })
            )
            
            body = json.loads(response['body'].read())
            return body['content'][0]['text']
        except Exception as e:
            print(f"Bedrock error: {e}")
            return "{}"
    
    def _update_incident(self, incident_id: str, plan: Dict, execution_result: Dict):
        """Update incident with remediation results"""
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
                            timeline = list_append(timeline, :event)
                    ''',
                    ExpressionAttributeNames={'#status': 'status'},
                    ExpressionAttributeValues={
                        ':status': 'resolved' if execution_result.get('status') == 'completed' else 'in_progress',
                        ':event': [{
                            'timestamp': int(datetime.now().timestamp()),
                            'event': 'remediation_executed',
                            'actor': 'remediation_agent',
                            'details': json.dumps({
                                'plan': plan,
                                'execution': execution_result
                            })
                        }]
                    }
                )
        except Exception as e:
            print(f"Error updating incident: {e}")

def lambda_handler(event, context):
    """Lambda handler for Remediation Agent"""
    
    print(f"Remediation Agent received: {json.dumps(event)}")
    
    try:
        incident_id = event.get('incident_id')
        incident_data = event.get('incident')
        root_cause = event.get('root_cause', {})
        
        if not incident_id or not incident_data:
            return {'statusCode': 400, 'error': 'Missing required fields'}
        
        agent = RemediationAgent()
        result = agent.remediate(incident_id, incident_data, root_cause)
        
        return {'statusCode': 200, 'result': result}
    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return {'statusCode': 500, 'error': str(e)}