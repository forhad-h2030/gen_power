#!/usr/bin/env python3
import socket
from PyComm.Tcp import ReceiveLines
import pyvisa  # DRY RUN
SMB_ETHERNET_ADDRESS = "TCPIP0::192.168.24.10::inst0::INSTR"

def main():
    host_svr = socket.gethostname()
    port_svr = 11111
    print(f"Wait on {host_svr}:{port_svr} (Ctrl+C to quit).")

    soc_svr = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    soc_svr.bind((host_svr, port_svr))
    soc_svr.listen(1)  # N of connections at once
    soc_svr.settimeout(1.0)  # accept() gives up every second, so Ctrl+C is noticed on Windows

    smb = pyvisa.ResourceManager().open_resource(SMB_ETHERNET_ADDRESS, timeout=5000)  # DRY RUN

    try:
        while True:
            try:
                soc, addr = soc_svr.accept()
            except socket.timeout:
                continue
            print("------------------------------------------------------------")
            print(f"Accept: {addr}.")

            msg = ReceiveLines(soc)

            print("---- Message ----")
            print(msg)
            print("-----------------")

            for line in msg.splitlines():
                cmd, _, arg = line.strip().partition(" ")
                values = [v.strip() for v in arg.split(",") if v.strip()]
                print(f"would send: {cmd}  {len(values)} values, {values}")
                print("line command goes into generator: ", line)
                #smb.write(line)  # DRY RUN
            soc.close()
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        soc_svr.close()
        smb.close()  # DRY RUN

if __name__ == "__main__":
    main()
