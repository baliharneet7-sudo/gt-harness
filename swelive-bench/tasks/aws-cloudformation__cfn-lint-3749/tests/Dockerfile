FROM starryzhang/sweb.eval.x86_64.aws-cloudformation_1776_cfn-lint-3749@sha256:f66404b8fee73c41820929afe4778e2c0dbba735a950ad9a042ae9e2ea649d29
WORKDIR /testbed
COPY test.sh run_tests.sh grade.py spec.json test_patch.diff /tests/
RUN chmod +x /tests/test.sh /tests/run_tests.sh
