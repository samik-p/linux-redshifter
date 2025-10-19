# linux-redshifter

## Usage

To run in background and detach from terminal:

```bash
nohup python3 pyflux_daemon.py &
```

To stop the script, first find the Process ID (PID):

```bash
ps aux | grep pyflux_daemon.py
```

Then, kill the process:

```bash
kill <PID>
```
