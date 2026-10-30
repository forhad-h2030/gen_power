#!/usr/bin/env python3
import socket
from PyComm.Tcp import ReceiveLines
# import pyvisa  # DRY RUN
SMB_ETHERNET_ADDRESS = "TCPIP0::192.168.24.10::inst0::INSTR"

def main():
    host_svr = socket.gethostname()
    port_svr = 11111
    print(f"Wait on {host_svr}:{port_svr}.")

    soc_svr = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    soc_svr.bind((host_svr, port_svr))
    soc_svr.listen(1)  # N of connections at once

    # smb = pyvisa.ResourceManager().open_resource(SMB_ETHERNET_ADDRESS, timeout=5000)  # DRY RUN

    while True:
        print("------------------------------------------------------------")
        soc, addr = soc_svr.accept()
        print(f"Accept: {addr}.")

        msg = ReceiveLines(soc)

        print("---- Message ----")
        print(msg)
        print("-----------------")

        for line in msg.splitlines():
            cmd, _, arg = line.strip().partition(" ")
            values = [v.strip() for v in arg.split(",") if v.strip()]
            print(f"would send: {cmd}  {len(values)} values, first {values[:3]}, last {values[-1:]}")
            # smb.write(line)  # DRY RUN
        soc.close()

if __name__ == "__main__":
    main()
