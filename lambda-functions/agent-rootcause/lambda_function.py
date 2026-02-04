"""
Root Cause Analysis Agent - AWS Nova Version
Uses ReAct pattern to investigate incidents systematically
"""

import json
import boto3
from datetime import datetime
from typing import Dict, List, Tuple

bedrock_runtime = boto3.client('bedrock-runtime', region_name='us-east-1')
lambda_client = boto3.client('lambda')
dynamodb = boto3.resource('dynamodb')

agent_state_table = dynamodb.Table('ITOps-AgentState')
incidents_table = dynamodb.Table('ITOps-Incidents')

class RootCauseAgent:
    """
    AI Agent for root cause analysis using ReAct pattern with AWS Nova
    """
    
    def __init__(self):
        self.agent_id = 'rootcause-agent'
        # AWS Nova Pro for complex reasoning
        self.model_id = 'amazon.nova-pro-v1:0'
        # Alternative: self.model_id = 'amazon.nova-lite-v1:0'
        self.max_iterations = 5
    
    def investigate(self, incident_id: str, incident_data: Dict) -> Dict:
        """
        Main investigation function using ReAct pattern
        
        ReAct Loop:
        1. Thought: Reason about what to do next
        2. Action: Execute a tool (MCP call)
        3. Observation: Analyze tool results
        4. Repeat until conclusion reached
        """
        
        investigation_log = []
        iteration = 0
        conclusion_reached = False
        root_cause = None
        
        # Initial context
        context = self._build_initial_context(incident_data)
        
        while iteration < self.max_iterations and not conclusion_reached:
            iteration += 1
            print(f"\n=== ReAct Iteration {iteration} ===")
            
            # Step 1: Thought (Reasoning)
            thought = self._generate_thought(context, investigation_log)
            investigation_log.append({'type': 'thought', 'content': thought})
            print(f"Thought: {thought}")
            
            # Step 2: Action (Tool Use)
            action = self._decide_action(thought, context)
            investigation_log.append({'type': 'action', 'content': action})
            print(f"Action: {action}")
            
            # Check if agent has reached conclusion
            if action.get('type') == 'conclude':
                conclusion_reached = True
                root_cause = action.get('conclusion')
                break
            
            # Step 3: Execute Action
            observation = self._execute_action(action)
            investigation_log.append({'type': 'observation', 'content': observation})
            print(f"Observation: {observation.get('summary', 'No summary')}")
            
            # Update context with new information
            context = self._update_context(context, observation)
        
        # Generate final report
        report = self._generate_report(incident_data, investigation_log, root_cause)
        
        # Update incident
        self._update_incident(incident_id, report)
        
        # Save state
        self._save_state(incident_id, investigation_log, report)
        
        return {
            'incident_id': incident_id,
            'root_cause': root_cause,
            'confidence': report['confidence'],
            'evidence': report['evidence'],
            'investigation_steps': len(investigation_log),
            'report': report
        }
    
    def _build_initial_context(self, incident: Dict) -> Dict:
        """Build initial investigation context"""
        return {
            'incident': incident,
            'known_facts': [
                f"Title: {incident.get('title')}",
                f"Description: {incident.get('description')}",
                f"Affected Services: {', '.join(incident.get('affected_services', []))}",
                f"Severity: {incident.get('severity', 'unknown')}"
            ],
            'gathered_data': {},
            'hypotheses': []
        }
    
    def _generate_thought(self, context: Dict, log: List[Dict]) -> str:
        """Generate next reasoning step"""
        
        prompt = f"""You are investigating an IT incident. Based on current information, reason about what to investigate next.

**Current Context:**
{json.dumps(context, indent=2)}

**Investigation So Far:**
{self._format_log(log)}

**Your Task:**
Reason about:
1. What do we know so far?
2. What are the most likely root causes?
3. What information is still missing?
4. What should we investigate next?

Provide your reasoning in 2-3 sentences."""

        response = self._call_bedrock(prompt, max_tokens=500)
        return response.strip()
    
    def _decide_action(self, thought: str, context: Dict) -> Dict:
        """Decide which action/tool to use next"""
        
        prompt = f"""Based on this reasoning, decide the next action.

**Reasoning:**
{thought}

**Available Actions:**
1. get_cpu_metrics - Check Lambda/EC2 CPU and performance metrics
2. get_error_logs - Retrieve error logs from CloudWatch
3. check_service_health - Get overall service health status
4. get_memory_metrics - Check memory utilization
5. conclude - Provide final root cause conclusion

**Context:**
{json.dumps(context, indent=2)}

Choose ONE action and provide parameters in this JSON format:
{{
  "type": "get_cpu_metrics|get_error_logs|check_service_health|get_memory_metrics|conclude",
  "parameters": {{...}} or "conclusion": "..." if concluding
}}

If you have enough evidence to identify the root cause, use "conclude" action with your conclusion."""

        response = self._call_bedrock(prompt, max_tokens=400)
        return self._parse_action(response)
    
    def _execute_action(self, action: Dict) -> Dict:
        """Execute the chosen action (call MCP tool)"""
        
        action_type = action.get('type')
        params = action.get('parameters', {})
        
        if action_type == 'conclude':
            return {'type': 'conclusion', 'summary': 'Investigation complete'}
        
        try:
            # Call appropriate MCP server
            if action_type in ['get_cpu_metrics', 'get_error_logs', 'check_service_health', 'get_memory_metrics']:
                response = lambda_client.invoke(
                    FunctionName='ITOps-MCP-Monitoring',
                    InvocationType='RequestResponse',
                    Payload=json.dumps({
                        'action': 'execute',
                        'tool_name': action_type,
                        'parameters': params
                    })
                )
                
                result = json.loads(response['Payload'].read())
                tool_result = result.get('result', {})
                
                return {
                    'type': 'tool_result',
                    'tool': action_type,
                    'data': tool_result,
                    'summary': self._summarize_tool_result(action_type, tool_result)
                }
            
            else:
                return {'type': 'error', 'summary': f'Unknown action: {action_type}'}
        
        except Exception as e:
            print(f"Error executing action: {e}")
            return {'type': 'error', 'summary': str(e)}
    
    def _summarize_tool_result(self, tool: str, result: Dict) -> str:
        """Create human-readable summary of tool results"""
        
        if tool == 'get_cpu_metrics':
            summary = result.get('summary', {})
            return f"CPU Metrics - Avg: {summary.get('avg', 0):.2f}%, Max: {summary.get('max', 0):.2f}%, Count: {summary.get('count', 0)} datapoints"
        
        elif tool == 'get_memory_metrics':
            summary = result.get('summary', {})
            return f"Memory Metrics - Avg: {summary.get('avg', 0):.2f}%, Max: {summary.get('max', 0):.2f}%"
        
        elif tool == 'get_error_logs':
            count = result.get('event_count', 0)
            return f"Found {count} error events in logs"
        
        elif tool == 'check_service_health':
            status = result.get('health_status', 'unknown')
            issues = result.get('issues', [])
            return f"Health: {status}, Issues: {', '.join(issues) if issues else 'None'}"
        
        return "Tool execution completed"
    
    def _update_context(self, context: Dict, observation: Dict) -> Dict:
        """Update investigation context with new observations"""
        
        if observation.get('type') == 'tool_result':
            tool_name = observation.get('tool')
            context['gathered_data'][tool_name] = observation.get('data')
        
        return context
    
    def _generate_report(self, incident: Dict, log: List[Dict], root_cause: str) -> Dict:
        """Generate comprehensive investigation report"""
        
        prompt = f"""Generate a comprehensive root cause analysis report.

**Incident:**
{json.dumps(incident, indent=2)}

**Investigation Log:**
{self._format_log(log)}

**Identified Root Cause:**
{root_cause}

Provide a report in this JSON format:
{{
  "root_cause": "Clear statement of root cause",
  "confidence": "high|medium|low",
  "evidence": ["Evidence 1", "Evidence 2", ...],
  "contributing_factors": ["Factor 1", "Factor 2", ...],
  "recommendations": ["Recommendation 1", "Recommendation 2", ...],
  "summary": "2-3 sentence executive summary"
}}"""

        response = self._call_bedrock(prompt, max_tokens=1500)
        return self._parse_report(response)
    
    def _parse_action(self, response: str) -> Dict:
        """Parse action JSON from Nova's response"""
        try:
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end > 0:
                return json.loads(response[start:end])
        except Exception as e:
            print(f"Error parsing action: {e}")
        
        # Fallback
        return {'type': 'check_service_health', 'parameters': {}}
    
    def _parse_report(self, response: str) -> Dict:
        """Parse report JSON from Nova's response"""
        try:
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end > 0:
                return json.loads(response[start:end])
        except Exception as e:
            print(f"Error parsing report: {e}")
        
        # Fallback
        return {
            'root_cause': 'Unable to determine definitively',
            'confidence': 'low',
            'evidence': [],
            'contributing_factors': [],
            'recommendations': ['Manual investigation required'],
            'summary': 'Automated analysis inconclusive'
        }
    
    def _format_log(self, log: List[Dict]) -> str:
        """Format investigation log for prompts"""
        formatted = []
        for entry in log:
            type_label = entry['type'].upper()
            content = entry.get('content')
            
            if isinstance(content, dict):
                content = json.dumps(content, indent=2)
            
            formatted.append(f"{type_label}: {content}")
        
        return '\n\n'.join(formatted)
    
    def _call_bedrock(self, prompt: str, max_tokens: int = 1000) -> str:
        """Call Bedrock with AWS Nova"""
        try:
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
                    "maxTokens": max_tokens,
                    "temperature": 0.5,
                    "topP": 0.9
                }
            )
            
            return response['output']['message']['content'][0]['text']
        except Exception as e:
            print(f"Bedrock Nova error: {e}")
            return "Error calling AI model"
    
    def _update_incident(self, incident_id: str, report: Dict):
        """Update incident with RCA results"""
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
                            'event': 'root_cause_analysis_completed',
                            'actor': 'rootcause_agent',
                            'details': json.dumps(report)
                        }]
                    }
                )
        except Exception as e:
            print(f"Error updating incident: {e}")
    
    def _save_state(self, incident_id: str, log: List[Dict], report: Dict):
        """Save agent state"""
        try:
            agent_state_table.put_item(
                Item={
                    'agent_id': f"{self.agent_id}_{incident_id}",
                    'timestamp': int(datetime.now().timestamp()),
                    'incident_id': incident_id,
                    'agent_type': 'rootcause',
                    'state': 'completed',
                    'investigation_log': log,
                    'report': report,
                    'ttl': int(datetime.now().timestamp()) + 604800
                }
            )
        except Exception as e:
            print(f"Error saving state: {e}")

def lambda_handler(event, context):
    """
    Lambda handler for Root Cause Agent
    Always return 'result' field for Step Functions compatibility
    """
    
    print(f"Root Cause Agent received: {json.dumps(event)}")
    
    try:
        incident_id = event.get('incident_id')
        incident_data = event.get('incident')
        
        if not incident_id or not incident_data:
            return {
                'statusCode': 400,
                'result': {
                    'incident_id': incident_id or 'unknown',
                    'root_cause': 'Unknown',
                    'confidence': 'low',
                    'evidence': [],
                    'investigation_steps': 0,
                    'report': {
                        'root_cause': 'Missing incident data',
                        'confidence': 'low',
                        'evidence': [],
                        'contributing_factors': [],
                        'recommendations': ['Provide valid incident data'],
                        'summary': 'Cannot perform RCA without incident data'
                    }
                }
            }
        
        agent = RootCauseAgent()
        result = agent.investigate(incident_id, incident_data)
        
        return {
            'statusCode': 200,
            'result': result
        }
    
    except Exception as e:
        print(f"Error in root cause agent: {e}")
        import traceback
        traceback.print_exc()
        
        return {
            'statusCode': 500,
            'result': {
                'incident_id': event.get('incident_id', 'unknown'),
                'root_cause': 'System error during investigation',
                'confidence': 'low',
                'evidence': [f'Error: {str(e)}'],
                'investigation_steps': 0,
                'report': {
                    'root_cause': 'System error prevented root cause analysis',
                    'confidence': 'low',
                    'evidence': [],
                    'contributing_factors': [str(e)],
                    'recommendations': ['Manual investigation required', 'Check Lambda logs'],
                    'summary': f'RCA agent encountered an error: {str(e)}'
                }
            }
        }