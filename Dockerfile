FROM python:3.9-buster AS base

RUN sh -c "$(curl -sSfL https://release.solana.com/v1.8.4/install)"

RUN apt-get update && apt-get -y install bc curl zlib1g-dev

RUN pip install --upgrade pip && pip --no-cache-dir install poetry

RUN mkdir /app 
COPY ./pyproject.toml ./poetry.lock ./

WORKDIR /app
ENV PYTHONPATH=${PYTHONPATH}:/app
ENV PATH="/app/bin:${PATH}:/app/scripts:/root/.local/share/solana/install/active_release/bin"

RUN poetry config virtualenvs.create false
RUN poetry install --no-dev --no-root

FROM base AS devel
# Have these as the last steps since the code here is the most-frequently changing
RUN pip install pytest
COPY . /app/
ARG LAST_COMMIT=""
RUN echo ${LAST_COMMIT} > /app/data/.version

FROM base AS pre-commit
# Have these as the last steps since the code here is the most-frequently changing
RUN pip install pytest
RUN pip install pre-commit
COPY .pre-commit-config.yaml /project/.pre-commit-config.yaml
COPY .git /app/.git

FROM base AS standard
# Have these as the last steps since the code here is the most-frequently changing
COPY . /app/
ARG LAST_COMMIT=""
RUN echo ${LAST_COMMIT} > /app/data/.version
