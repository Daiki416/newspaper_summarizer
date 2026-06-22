# AWS Lambda（コンテナイメージ）用の Dockerfile。
# 既存の CLI ロジックをそのまま Lambda 上で動かす。

FROM public.ecr.aws/lambda/python:3.13

# 依存ライブラリを先にインストールする（レイヤーキャッシュを効かせるため）
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r requirements.txt

# アプリコードは src/ 配下に、設定ファイルは config/ 配下に配置する。
# fetcher.py の CONFIG_PATH は Path(__file__).parent.parent / "config" / "sources.yaml" のため、
# fetcher.py を ${LAMBDA_TASK_ROOT}/src/ に置くと parent.parent が ${LAMBDA_TASK_ROOT} となり
# ${LAMBDA_TASK_ROOT}/config/sources.yaml に到達できる。
COPY src/ ${LAMBDA_TASK_ROOT}/src/
COPY config/ ${LAMBDA_TASK_ROOT}/config/

# bare import（from fetcher import ... など）を成立させるため src/ を import パスに通す。
ENV PYTHONPATH=${LAMBDA_TASK_ROOT}/src

# ハンドラ指定（lambda_function.py は ${LAMBDA_TASK_ROOT}/src/ に置かれ PYTHONPATH 経由で解決される）
CMD ["lambda_function.handler"]
