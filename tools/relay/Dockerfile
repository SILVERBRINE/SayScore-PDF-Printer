FROM python:3.12-alpine
LABEL sayscore.relay.version="5"
WORKDIR /relay
COPY network_relay.py /relay/network_relay.py
ENTRYPOINT ["python3", "/relay/network_relay.py"]
