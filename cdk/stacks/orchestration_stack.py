from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    aws_lambda as _lambda,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
)
from constructs import Construct


class OrchestrationStackProps:
    """Props for OrchestrationStack accepting Lambda function references from ComputeStack."""

    def __init__(
        self,
        destination_researcher_fn: _lambda.IFunction,
        budget_optimizer_fn: _lambda.IFunction,
        weather_analyzer_fn: _lambda.IFunction,
        experience_curator_fn: _lambda.IFunction,
        merge_fn: _lambda.IFunction,
        fallback_fn: _lambda.IFunction,
        status_update_fn: _lambda.IFunction,
    ) -> None:
        self.destination_researcher_fn = destination_researcher_fn
        self.budget_optimizer_fn = budget_optimizer_fn
        self.weather_analyzer_fn = weather_analyzer_fn
        self.experience_curator_fn = experience_curator_fn
        self.merge_fn = merge_fn
        self.fallback_fn = fallback_fn
        self.status_update_fn = status_update_fn


class OrchestrationStack(Stack):
    """Stack for Step Functions state machine with Parallel state and Retry/Catch configuration.

    Defines a Standard workflow:
    ValidateInput -> UpdateStatusStarted -> ParallelAgents -> MergeResults -> UpdateStatusComplete
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        orchestration_props: OrchestrationStackProps | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if orchestration_props is None:
            return

        self._props = orchestration_props
        self.state_machine = self._build_state_machine()

        CfnOutput(
            self,
            "StateMachineArn",
            value=self.state_machine.state_machine_arn,
            description="Step Functions state machine ARN",
            export_name="TravelConciergeStateMachineArn",
        )

    def _build_state_machine(self) -> sfn.StateMachine:
        validate_input = sfn.Pass(
            self,
            "ValidateInput",
            comment="Structure the trip request input for downstream agents",
            parameters={
                "itinerary_id.$": "$.itinerary_id",
                "trip_request.$": "$.trip_request",
            },
        )

        update_status_started = self._create_status_update_task(
            "UpdateStatusStarted", status="started",
        )

        parallel_agents = self._build_parallel_agents()

        merge_results = tasks.LambdaInvoke(
            self,
            "MergeResults",
            lambda_function=self._props.merge_fn,
            comment="Merge all agent outputs into a cohesive itinerary and persist to storage",
            payload=sfn.TaskInput.from_object({
                "itinerary_id.$": "$.itinerary_id",
                "trip_request.$": "$.trip_request",
                "agent_outputs.$": "$.agent_outputs",
            }),
            result_path="$.merge_result",
            payload_response_only=True,
        )

        update_status_complete = self._create_status_update_task(
            "UpdateStatusComplete", status="completed",
        )

        definition = (
            validate_input
            .next(update_status_started)
            .next(parallel_agents)
            .next(merge_results)
            .next(update_status_complete)
        )

        return sfn.StateMachine(
            self,
            "TravelConciergeWorkflow",
            definition_body=sfn.DefinitionBody.from_chainable(definition),
            state_machine_type=sfn.StateMachineType.STANDARD,
            timeout=Duration.seconds(300),
            comment="AI Travel Concierge orchestration workflow with parallel agent execution",
        )

    def _create_status_update_task(self, state_id: str, status: str) -> tasks.LambdaInvoke:
        return tasks.LambdaInvoke(
            self,
            state_id,
            lambda_function=self._props.status_update_fn,
            comment=f"Update workflow status to '{status}'",
            payload=sfn.TaskInput.from_object({
                "itinerary_id.$": "$.itinerary_id",
                "status": status,
            }),
            result_path=sfn.JsonPath.DISCARD,
            payload_response_only=True,
        )

    def _build_parallel_agents(self) -> sfn.Parallel:
        parallel = sfn.Parallel(
            self,
            "ParallelAgents",
            comment="Execute all four AI agents in parallel",
            result_path="$.agent_outputs",
        )

        for agent_name, agent_fn in [
            ("DestinationResearcher", self._props.destination_researcher_fn),
            ("BudgetOptimizer", self._props.budget_optimizer_fn),
            ("WeatherAnalyzer", self._props.weather_analyzer_fn),
            ("ExperienceCurator", self._props.experience_curator_fn),
        ]:
            parallel.branch(self._build_agent_branch(agent_name, agent_fn))

        return parallel

    def _build_agent_branch(
        self, agent_name: str, agent_fn: _lambda.IFunction,
    ) -> sfn.Chain:
        fallback_task = tasks.LambdaInvoke(
            self,
            f"{agent_name}Fallback",
            lambda_function=self._props.fallback_fn,
            comment=f"Fallback handler for {agent_name}",
            payload=sfn.TaskInput.from_object({
                "itinerary_id.$": "$.itinerary_id",
                "trip_request.$": "$.trip_request",
                "agent_name": agent_name,
                "error.$": "$.error",
            }),
            payload_response_only=True,
            result_path="$",
        )

        agent_task = tasks.LambdaInvoke(
            self,
            f"{agent_name}Invoke",
            lambda_function=agent_fn,
            comment=f"Invoke {agent_name} agent",
            payload=sfn.TaskInput.from_object({
                "itinerary_id.$": "$.itinerary_id",
                "trip_request.$": "$.trip_request",
            }),
            payload_response_only=True,
            result_path="$",
        )

        agent_task.add_retry(
            errors=["States.TaskFailed", "States.Timeout"],
            interval=Duration.seconds(2),
            max_attempts=3,
            backoff_rate=2.0,
            jitter_strategy=sfn.JitterType.FULL,
        )

        agent_task.add_catch(
            handler=fallback_task,
            errors=["States.ALL"],
            result_path="$.error",
        )

        return sfn.Chain.start(agent_task)
