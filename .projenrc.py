from projen.awscdk import AwsCdkPythonApp

project = AwsCdkPythonApp(
    author_email="no-reply@dontsendmemails.com",
    author_name="Yvo van Zee",
    cdk_version="2.148.1",
    module_name="codechecker",
    name="codechecker",
    version="0.1.0",
    deps=["boto3>=1.35.0, <2.0.0"],
)

project.synth()
