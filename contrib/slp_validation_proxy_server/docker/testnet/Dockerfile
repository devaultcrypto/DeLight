FROM ubuntu:18.04
  
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update
RUN apt-get install -y git curl nano gnupg wget
RUN apt-get install -y python3-pip python3-setuptools expect

RUN git clone -b 3.4.4 https://github.com/simpleledger/Electron-Cash-SLP.git && \
    cd Electron-Cash-SLP && \
    python3 setup.py install && \
    apt-get -y install protobuf-compiler && \
    protoc --proto_path=lib/ --python_out=lib/ lib/paymentrequest.proto

COPY ./config /Electron-Cash-SLP/testnet/config
COPY ./create_wallet.sh /Electron-Cash-SLP/create_wallet.sh
COPY ./start_daemon.sh /Electron-Cash-SLP/start_daemon.sh

WORKDIR /Electron-Cash-SLP

RUN ./create_wallet.sh

EXPOSE 5112

#CMD ["/bin/bash"]
CMD ["./start_daemon.sh"]