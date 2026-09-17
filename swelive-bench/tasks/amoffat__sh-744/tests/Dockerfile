FROM starryzhang/sweb.eval.x86_64.amoffat_1776_sh-744@sha256:0ab5f01f2c45fe84813deec1dd1478917ba63b9a2a7443dc43a065bd186e14c3
WORKDIR /testbed
COPY test.sh run_tests.sh grade.py spec.json test_patch.diff /tests/
RUN chmod +x /tests/test.sh /tests/run_tests.sh
