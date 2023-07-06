# Set base image (host OS)
FROM python:3.10-slim-bullseye

# Set the working directory in the container
WORKDIR /Riakmaw/

# Install all required packages
RUN apt-get -qq update && apt-get -qq upgrade -y
RUN apt-get -qq install -y --no-install-recommends \
    git curl

# copy pyproject.toml and poetry.lock for layer caching
COPY pyproject.toml poetry.lock ./

# ignore pip root user warning
ENV PIP_ROOT_USER_ACTION=ignore

RUN pip install --upgrade pip \
    && pip install poetry

RUN poetry install --no-root --only main -E uvloop

ARG USERBOTINDO_ACCESS_TOKEN
COPY ./preinstall.sh ./
RUN chmod +x ./preinstall.sh
RUN ./preinstall.sh

# copy the rest of files
COPY . .

CMD ["poetry", "run", "Riakmaw"]
