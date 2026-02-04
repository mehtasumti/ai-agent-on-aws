"""
Triage Agent - AWS Nova Version
"""

import json
import boto3
from datetime import datetime
from typing import Dict, List

bedrock_runtime = boto3.client('bedrock-runtime', region_name='us-east-1')
lambda_client = boto3.client('lambda')
dynamodb = boto3.resource('dynamodb')

agent_state_table = dynamodb.Table('ITOps-AgentState')
incidents_table = dynamodb.Table('ITOps-Incidents')

class TriageAgent:
    """
    AI Agent for incident triage using AWS Nova
    """
    
    def __init__(self):
        self.agent_id = 'triage-agent'
        # AWS Nova Pro - Most capable Nova model
        self.model_id = 'amazon.nova-pro-v1:0'
        # Alternative options:
        # self.model_id = 'amazon.nova-lite-v1:0'  # Faster, cheaper
        # self.model_id = 'amazon.nova-micro-v1:0' # Fastest, cheapest
    
    def triage_incident(self, incident_id: str, incident_data: Dict) -> Dict:
        """Main triage function"""
        
        # Build triage prompt
        prompt = self._build_triage_prompt(incident_data)
        
        # Get triage assessment from Nova
        assessment = self._call_bedrock(prompt)
        
        # Parse assessment
        parsed = self._parse_assessment(assessment)
        
        # Update incident with triage results
        self._update_incident(incident_id, parsed)
        
        # Save agent state
        self._save_state(incident_id, parsed)
        
        return {
            'incident_id': incident_id,
            'severity': parsed['severity'],
            'routing': parsed['routing'],
            'reasoning': parsed['reasoning'],
            'next_steps': parsed['next_steps']
        }
    
    def _build_triage_prompt(self, incident: Dict) -> str:
        """Build the triage prompt for Nova"""
        
        return f"""You are an expert IT operations triage agent. Analyze this incident and provide a triage assessment.

**Incident Information:**
- Title: {incident.get('title', 'Unknown')}
- Description: {incident.get('description', 'No description')}
- Affected Services: {', '.join(incident.get('affected_services', ['Unknown']))}
- Detected By: {incident.get('detected_by', 'Unknown')}
- Severity: {incident.get('severity', 'unknown')}

**Your Task:**
1. Assess the incident severity (critical, high, medium, or low)
2. Determine routing (escalate, investigate, auto_resolve)
3. Provide clear reasoning for your assessment
4. Suggest immediate next steps

**Severity Guidelines:**
- **Critical**: Complete system outage, data loss, security breach affecting multiple users
- **High**: Partial outage, significant performance degradation, affecting specific user groups
- **Medium**: Minor issues, degraded functionality, affecting few users
- **Low**: Cosmetic issues, documentation gaps, non-urgent improvements

**Routing Guidelines:**
- **escalate**: Critical incidents needing immediate human attention
- **investigate**: Incidents requiring root cause analysis by AI agent
- **auto_resolve**: Simple issues with known solutions

Provide your assessment in this exact JSON format:
{{
  "severity": "critical|high|medium|low",
  "routing": "escalate|investigate|auto_resolve",
  "reasoning": "Detailed explanation of your assessment",
  "next_steps": ["Step 1", "Step 2", "Step 3"],
  "estimated_impact": "Description of potential impact",
  "urgency_score": 5
}}

Be thorough but concise. Focus on actionable insights."""

    def _call_bedrock(self, prompt: str) -> str:
        """Call Bedrock with AWS Nova"""
        
        try:
            # Nova uses the Converse API
            response = bedrock_runtime.converse(
                modelId=self.model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "text": prompt
                            }
                        ]
                    }
                ],
                inferenceConfig={
                    "maxTokens": 2000,
                    "temperature": 0.3,
                    "topP": 0.9
                }
            )
            
            # Extract text from Nova response
            return response['output']['message']['content'][0]['text']
        
        except Exception as e:
            print(f"Error calling Bedrock Nova: {e}")
            # Return a fallback response instead of raising
            return json.dumps({
                "severity": "medium",
                "routing": "investigate",
                "reasoning": f"Bedrock API error: {str(e)}. Defaulting to safe triage.",
                "next_steps": ["Manual review required", "Check Bedrock permissions"],
                "estimated_impact": "Unknown - automatic triage failed",
                "urgency_score": 5
            })
    
    def _parse_assessment(self, assessment_text: str) -> Dict:
        """Parse the JSON assessment from Nova's response"""
        
        try:
            # Extract JSON from response
            start_idx = assessment_text.find('{')
            end_idx = assessment_text.rfind('}') + 1
            
            if start_idx == -1 or end_idx == 0:
                raise ValueError("No JSON found in response")
            
            json_str = assessment_text[start_idx:end_idx]
            parsed = json.loads(json_str)
            
            # Validate required fields
            required = ['severity', 'routing', 'reasoning', 'next_steps']
            for field in required:
                if field not in parsed:
                    raise ValueError(f"Missing required field: {field}")
            
            return parsed
        
        except Exception as e:
            print(f"Error parsing assessment: {e}")
            print(f"Raw assessment: {assessment_text}")
            
            # Fallback to safe defaults
            return {
                'severity': 'medium',
                'routing': 'investigate',
                'reasoning': 'Error parsing AI response, defaulting to safe triage',
                'next_steps': ['Manual review required'],
                'estimated_impact': 'Unknown',
                'urgency_score': 5
            }
    
    def _update_incident(self, incident_id: str, assessment: Dict):
        """Update incident with triage results"""
        
        try:
            response = incidents_table.query(
                KeyConditionExpression='incident_id = :id',
                ExpressionAttributeValues={':id': incident_id}
            )
            
            if not response.get('Items'):
                print(f"Incident {incident_id} not found in DynamoDB")
                return
            
            created_at = response['Items'][0]['created_at']
            
            incidents_table.update_item(
                Key={
                    'incident_id': incident_id,
                    'created_at': created_at
                },
                UpdateExpression='''
                    SET severity = :severity,
                        assigned_to = :assigned_to,
                        timeline = list_append(if_not_exists(timeline, :empty_list), :timeline_event)
                ''',
                ExpressionAttributeValues={
                    ':severity': assessment['severity'],
                    ':assigned_to': assessment['routing'],
                    ':empty_list': [],
                    ':timeline_event': [{
                        'timestamp': int(datetime.now().timestamp()),
                        'event': 'triage_completed',
                        'actor': 'triage_agent',
                        'details': json.dumps(assessment)
                    }]
                }
            )
        
        except Exception as e:
            print(f"Error updating incident: {e}")
    
    def _save_state(self, incident_id: str, assessment: Dict):
        """Save agent state for tracking"""
        
        try:
            agent_state_table.put_item(
                Item={
                    'agent_id': f"{self.agent_id}_{incident_id}",
                    'timestamp': int(datetime.now().timestamp()),
                    'incident_id': incident_id,
                    'agent_type': 'triage',
                    'state': 'completed',
                    'assessment': assessment,
                    'ttl': int(datetime.now().timestamp()) + 604800
                }
            )
        
        except Exception as e:
            print(f"Error saving state: {e}")

def lambda_handler(event, context):
    """
    Lambda handler for Triage Agent
    Always return 'result' field for Step Functions compatibility
    """
    
    print(f"Triage Agent received: {json.dumps(event)}")
    
    try:
        incident_id = event.get('incident_id')
        incident_data = event.get('incident')
        
        if not incident_id or not incident_data:
            return {
                'statusCode': 400,
                'result': {
                    'incident_id': incident_id or 'unknown',
                    'severity': 'unknown',
                    'routing': 'escalate',
                    'reasoning': 'Missing incident_id or incident data in request',
                    'next_steps': ['Fix request format']
                }
            }
        
        # Create agent and perform triage
        agent = TriageAgent()
        result = agent.triage_incident(incident_id, incident_data)
        
        return {
            'statusCode': 200,
            'result': result
        }
    
    except Exception as e:
        print(f"Error in triage agent: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'result': {
                'incident_id': event.get('incident_id', 'unknown'),
                'severity': 'high',
                'routing': 'escalate',
                'reasoning': f'System error in triage agent: {str(e)}',
                'next_steps': ['Manual intervention required', 'Check Lambda logs']
            }
        }