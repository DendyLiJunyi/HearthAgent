"""MAKCU text protocol over the USB2 serial port."""


class MakcuError(RuntimeError):
    pass


class Makcu:
    USB_ID = (0x1A86, 0x55D3)
    BAUD_RATES = (115200, 4000000)
    ACK_TIMEOUT = 0.05

    def __init__(self, serial_port):
        self.serial = serial_port

    @classmethod
    def connect(cls, port=None, baud=None):
        try:
            import serial
            from serial.tools import list_ports
        except ImportError as error:
            raise MakcuError('pyserial is missing. Run scripts/setup-laya.ps1 to update the runtime.') from error

        if port is None:
            try:
                candidates = sorted(p.device for p in list_ports.comports() if (p.vid, p.pid) == cls.USB_ID)
            except OSError as error:
                raise MakcuError(f'Could not list serial ports: {error}. Specify --makcu-port COMx.') from error
            if len(candidates) != 1:
                found = ', '.join(candidates) or 'none'
                raise MakcuError(f'Expected one MAKCU serial candidate, found {found}. Specify --makcu-port COMx.')
            port = candidates[0]

        failures = []
        for rate in (baud,) if baud is not None else cls.BAUD_RATES:
            try:
                connection = cls(serial.Serial(port, rate, timeout=0.25, write_timeout=0.25))
            except (OSError, ValueError) as error:
                failures.append(f'{rate}: {error}')
                continue
            connected = False
            try:
                connection.serial.reset_input_buffer()
                connection._query(b'km.version()', (b'MAKCU',), attempts=1)
                connected = True
                return connection
            except (OSError, MakcuError) as error:
                failures.append(f'{rate}: {error}')
            finally:
                if not connected:
                    connection.close()
        raise MakcuError(f'MAKCU handshake failed on {port} ({", ".join(failures)})')

    def _write(self, command):
        payload = command + b'\r'
        if self.serial.write(payload) != len(payload):
            raise MakcuError('short serial write')

    def _read_reply(self, results):
        for _ in range(4):
            reply = self.serial.read_until(b'>>>', size=512)
            lines = [line.strip().removeprefix(b'km.') for line in reply.removesuffix(b'>>>').splitlines()]
            if b'ERR' in lines:
                raise MakcuError('device rejected the command')
            if not reply.endswith(b'>>>'):
                return None
            result = next((line for line in lines if line in results), None)
            if result is not None:
                return result
        return None

    def _query(self, query, results, *, attempts=2):
        for _ in range(attempts):
            self._write(query)
            result = self._read_reply(results)
            if result is not None:
                return result
        raise MakcuError(f'missing MAKCU reply to {query.decode("ascii")}')

    def _send(self, command, query=None, results=(b'MAKCU',)):
        wire = command.encode('ascii')
        try:
            self._write(wire)
            timeout = self.serial.timeout
            self.serial.timeout = self.ACK_TIMEOUT
            try:
                echoed = self._read_reply((wire.removeprefix(b'km.'),))
            finally:
                self.serial.timeout = timeout
            if query is not None:
                return self._query(query, results)
            if echoed is None:
                # Firmware with echo disabled needs a separate read-only confirmation.
                self._query(b'km.version()', (b'MAKCU',))
        except (OSError, MakcuError) as error:
            raise MakcuError(f'{self.serial.port}: {command}: {error}') from error

    def command(self, command):
        self._send(command)

    def release(self, button):
        state = self._send(f'km.{button}(0)', f'km.{button}()'.encode('ascii'), (b'0', b'1', b'2', b'3'))
        if int(state) & 2:
            raise MakcuError(f'{self.serial.port}: {button} button is still held by MAKCU')

    def close(self):
        self.serial.close()
