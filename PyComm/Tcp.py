#!/usr/bin/python3
import socket

def SendLine(socket, string):
    socket.send(bytes(string+"\n", 'utf-8'))

def ReceiveLine(socket, bytes_extra=b'', alive=True, recv_size=256):
    line = bytearray(bytes_extra)
    if line.find(b'\n') < 0 and alive:
        while True:
            try:
                buffer = socket.recv(recv_size)
                line.extend(buffer)
                if len(buffer) == 0 or b'\n' in buffer:
                    break
            except Exception as err:
                print(f"Exception: {err}, {type(err)}")
                alive = False
                break

    pos_nl = line.find(b'\n')
    if pos_nl < 0:
        return None, b'', alive
#        return line.decode("utf-8"), b'', alive
    else:
        return line[:pos_nl].decode("utf-8"), line[pos_nl+1:], alive

def ReceiveLines(socket, bytes_extra=b'', term_line='EOT', recv_size=256):
    alive = True
    msg = ''
    while True:
        line, bytes_extra, alive = ReceiveLine(socket, bytes_extra, alive)
        if line == term_line or line == None:
            break
        msg += line + "\n"
    return msg

def ReceiveLineList(socket, bytes_extra=b'', term_line='EOT', recv_size=256):
    alive = True
    line_list = []
    while True:
        line, bytes_extra, alive = ReceiveLine(socket, bytes_extra, alive)
        if line == term_line or line == None:
            break
        line_list.append(line)
    return line_list

# ---- added for gen_power (the functions above are left unchanged) ----

def SendLines(soc, lines, term_line='EOT'):
    """Send the lines and the terminator in one go. sendall, so a long message is never cut short."""
    soc.sendall(("\n".join(list(lines) + [term_line]) + "\n").encode("utf-8"))

def ReceiveLineStop(soc, stop, bytes_extra=b'', recv_size=4096):
    """Like ReceiveLine, but it checks stop (a threading.Event) once a second, so Ctrl+C and a Stop button still work.
    Returns (line, bytes_extra, alive). line is None when the client closed the connection or stop was set;
    bytes_extra holds whatever arrived after the line, so nothing is lost between lines."""
    soc.settimeout(1.0)
    buf = bytes_extra
    while b'\n' not in buf:
        if stop.is_set():
            return None, buf, True
        try:
            data = soc.recv(recv_size)
        except socket.timeout:
            continue
        except OSError as err:
            print(f"Exception: {err}, {type(err)}")
            return None, buf, False
        if not data:
            return None, buf, False
        buf += data
    line, _, rest = buf.partition(b'\n')
    return line.decode("utf-8", errors="replace"), rest, True
