FROM starryzhang/sweb.eval.x86_64.arviz-devs_1776_arviz-2413@sha256:ba0f72743455df00addcdfdfe326e3645761a019b166652318a5c828f1231a80
WORKDIR /testbed
COPY test.sh run_tests.sh grade.py spec.json test_patch.diff /tests/
RUN chmod +x /tests/test.sh /tests/run_tests.sh
