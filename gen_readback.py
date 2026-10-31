#!/usr/bin/env python3
import pyvisa

SMB_ETHERNET_ADDRESS = "TCPIP0::192.168.24.10::inst0::INSTR"
QUERIES = [
    "OUTPut:STATe?",
    "SOURce:FREQuency:MODE?",
    "SOURce:FREQuency?",
    "SOURce:POWer:LEVel?",
    "SOURce:LIST:SELect?",
    "SOURce:LIST:MODE?",
    "SOURce:LIST:TRIGger:SOURce?",
    "SOURce:LIST:FREQuency:POINts?",
    "SOURce:LIST:POWer:POINts?",
    "SOURce:LIST:DWELl?",
    "SOURce:LIST:FREQuency?",
    "SOURce:LIST:POWer?",
    "SYSTem:ERRor?",
]

def main():
    smb = pyvisa.ResourceManager().open_resource(SMB_ETHERNET_ADDRESS, timeout=5000)
    try:
        print(f"Connected to RF Gen: {smb.query('*IDN?').strip()}")
        for q in QUERIES:
            try:
                print(f"{q:34} {smb.query(q).strip()}")
            except pyvisa.VisaIOError as e:  
                print(f"{q:34} no answer: {e}")
    finally:
        smb.close()

if __name__ == "__main__":
    main()
