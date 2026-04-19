"""Tests for OrchestrationStack Step Functions state machine definition."""

import json

import aws_cdk as cdk
import aws_cdk.assertions as assertions
from aws_cdk import aws_lambda as _lambda

from Agentic_AI_With_step_functions.cdk.stacks.orchestration_stack import OrchestrationStack, OrchestrationStackProps


def _create_test_stack() -> tuple[cdk.App, OrchestrationStack]:
    """Create a test stack with mock Lambda functions wired into OrchestrationStack."""
    app = cdk.App()

    # Helper stack to create mock Lambda functions
    helper = cdk.Stack(app, "HelperStack")

    def make_fn(fn_id: str) -> _lambda.Function:
        return _lambda.Function(
            helper,
            fn_id,
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_inline("def handler(event, ctx): pass"),
        )

    props = OrchestrationStackProps(
        destination_researcher_fn=make_fn("DestResearcherFn"),
        budget_optimizer_fn=make_fn("BudgetOptimizerFn"),
        weather_analyzer_fn=make_fn("WeatherAnalyzerFn"),
        experience_curator_fn=make_fn("ExperienceCuratorFn"),
        merge_fn=make_fn("MergeFn"),
        fallback_fn=make_fn("FallbackFn"),
        status_update_fn=make_fn("StatusUpdateFn"),
    )

    stack = OrchestrationStack(
        app,
        "TestOrchestrationStack",
        orchestration_props=props,
    )
    return app, stack


def test_state_machine_is_created():
    """State machine resource exists in the synthesized template."""
    _, stack = _create_test_stack()
    template = assertions.Template.from_stack(stack)
    template.resource_count_is("AWS::StepFunctions::StateMachine", 1)


def test_state_machine_is_standard_type():
    """State machine uses STANDARD type for long-running executions."""
    _, stack = _create_test_stack()
    template = assertions.Template.from_stack(stack)
    template.has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        {"StateMachineType": "STANDARD"},
    )


def test_state_machine_definition_has_all_states():
    """State machine definition contains all required states in the workflow."""
    _, stack = _create_test_stack()
    template = assertions.Template.from_stack(stack)

    resources = template.find_resources("AWS::StepFunctions::StateMachine")
    assert len(resources) == 1

    sm_resource = list(resources.values())[0]
    definition_string = sm_resource["Properties"]["DefinitionString"]

    # Resolve Fn::Join to get the actual definition
    resolved = _resolve_definition(definition_string)
    definition = json.loads(resolved)

    states = definition.get("States", {})
    assert "ValidateInput" in states
    assert "UpdateStatusStarted" in states
    assert "ParallelAgents" in states
    assert "MergeResults" in states
    assert "UpdateStatusComplete" in states


def test_parallel_state_has_four_branches():
    """ParallelAgents state has exactly 4 branches (one per agent)."""
    _, stack = _create_test_stack()
    template = assertions.Template.from_stack(stack)

    resources = template.find_resources("AWS::StepFunctions::StateMachine")
    sm_resource = list(resources.values())[0]
    resolved = _resolve_definition(sm_resource["Properties"]["DefinitionString"])
    definition = json.loads(resolved)

    parallel_state = definition["States"]["ParallelAgents"]
    assert parallel_state["Type"] == "Parallel"
    assert len(parallel_state["Branches"]) == 4


def test_agent_branches_have_retry_config():
    """Each agent branch has retry configuration with correct parameters."""
    _, stack = _create_test_stack()
    template = assertions.Template.from_stack(stack)

    resources = template.find_resources("AWS::StepFunctions::StateMachine")
    sm_resource = list(resources.values())[0]
    resolved = _resolve_definition(sm_resource["Properties"]["DefinitionString"])
    definition = json.loads(resolved)

    parallel_state = definition["States"]["ParallelAgents"]
    for branch in parallel_state["Branches"]:
        # Find the invoke state (first state in the branch)
        first_state_name = branch["StartAt"]
        invoke_state = branch["States"][first_state_name]

        assert "Retry" in invoke_state, f"Missing Retry in {first_state_name}"
        # CDK adds a default Lambda service retry as the first entry;
        # our custom retry for States.TaskFailed/States.Timeout follows it.
        custom_retries = [
            r for r in invoke_state["Retry"]
            if "States.TaskFailed" in r.get("ErrorEquals", [])
        ]
        assert len(custom_retries) == 1, f"Expected 1 custom retry in {first_state_name}"
        retry = custom_retries[0]
        assert "States.TaskFailed" in retry["ErrorEquals"]
        assert "States.Timeout" in retry["ErrorEquals"]
        assert retry["IntervalSeconds"] == 2
        assert retry["MaxAttempts"] == 3
        assert retry["BackoffRate"] == 2.0
        assert retry.get("JitterStrategy") == "FULL"


def test_agent_branches_have_catch_config():
    """Each agent branch has catch configuration routing to a fallback state."""
    _, stack = _create_test_stack()
    template = assertions.Template.from_stack(stack)

    resources = template.find_resources("AWS::StepFunctions::StateMachine")
    sm_resource = list(resources.values())[0]
    resolved = _resolve_definition(sm_resource["Properties"]["DefinitionString"])
    definition = json.loads(resolved)

    parallel_state = definition["States"]["ParallelAgents"]
    for branch in parallel_state["Branches"]:
        first_state_name = branch["StartAt"]
        invoke_state = branch["States"][first_state_name]

        assert "Catch" in invoke_state, f"Missing Catch in {first_state_name}"
        catch = invoke_state["Catch"][0]
        assert "States.ALL" in catch["ErrorEquals"]
        assert "$.error" == catch["ResultPath"]
        # The catch should route to a fallback state that exists in this branch
        assert catch["Next"] in branch["States"]


def test_workflow_chain_order():
    """States are chained in the correct order."""
    _, stack = _create_test_stack()
    template = assertions.Template.from_stack(stack)

    resources = template.find_resources("AWS::StepFunctions::StateMachine")
    sm_resource = list(resources.values())[0]
    resolved = _resolve_definition(sm_resource["Properties"]["DefinitionString"])
    definition = json.loads(resolved)

    states = definition["States"]
    assert definition["StartAt"] == "ValidateInput"
    assert states["ValidateInput"]["Next"] == "UpdateStatusStarted"
    assert states["UpdateStatusStarted"]["Next"] == "ParallelAgents"
    assert states["ParallelAgents"]["Next"] == "MergeResults"
    assert states["MergeResults"]["Next"] == "UpdateStatusComplete"
    assert states["UpdateStatusComplete"].get("End") is True


def test_no_state_machine_without_props():
    """Stack without props should not create any state machine."""
    app = cdk.App()
    stack = OrchestrationStack(app, "EmptyStack")
    template = assertions.Template.from_stack(stack)
    template.resource_count_is("AWS::StepFunctions::StateMachine", 0)


def _resolve_definition(definition_string: dict) -> str:
    """Resolve a CloudFormation Fn::Join into a plain string for testing.

    Replaces intrinsic function tokens (Ref, Fn::GetAtt, Fn::ImportValue)
    with placeholder ARNs so the JSON can be parsed.
    """
    if "Fn::Join" in definition_string:
        separator = definition_string["Fn::Join"][0]
        parts = definition_string["Fn::Join"][1]
        resolved_parts = []
        for part in parts:
            if isinstance(part, str):
                resolved_parts.append(part)
            elif isinstance(part, dict):
                # All intrinsic functions resolve to a placeholder ARN
                resolved_parts.append(
                    "arn:aws:lambda:us-east-1:123456789012:function:placeholder"
                )
            else:
                resolved_parts.append(str(part))
        return separator.join(resolved_parts)
    return json.dumps(definition_string)
