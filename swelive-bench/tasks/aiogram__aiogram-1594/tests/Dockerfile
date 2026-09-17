FROM starryzhang/sweb.eval.x86_64.aiogram_1776_aiogram-1594@sha256:4461f94ae2293dcbabcd71b2425a9d00f9d88dba0e0203fecba6aee311199c2d
WORKDIR /testbed
COPY test.sh run_tests.sh grade.py spec.json test_patch.diff /tests/
RUN chmod +x /tests/test.sh /tests/run_tests.sh
