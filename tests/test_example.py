import pytest
from aws_cdk import App
from aws_cdk.assertions import Template

from codechecker.main import CodeChecker

@pytest.fixture(scope='module')
def template():
  app = App()
  stack = CodeChecker(
      app,
      "codechecker-test",
      approvals_per_branch={"main": 2}
  )
  template = Template.from_stack(stack)
  yield template

def test_no_buckets_found(template):
  template.resource_count_is("AWS::S3::Bucket", 0)

def test_lambda_function_exists(template):
  template.resource_count_is("AWS::Lambda::Function", 1)

def test_sns_topic_exists(template):
  template.resource_count_is("AWS::SNS::Topic", 1)

def test_codebuild_project_exists(template):
  # Should have one CodeBuild project for the 'main' branch
  template.resource_count_is("AWS::CodeBuild::Project", 1)

def test_kms_keys_exist(template):
  # Should have KMS keys for SNS, Lambda, and CodeBuild
  template.resource_count_is("AWS::KMS::Key", 3)
