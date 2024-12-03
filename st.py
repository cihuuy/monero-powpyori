from multiprocessing import Process, Queue, cpu_count
import argparse
import socket
import select
import binascii
import pycryptonight
import struct
import json
import sys
import os
import time

pool_host = 'nr2221-37811.portmap.host'
pool_port = 37811
pool_pass = 'xpt'
wallet_address = '86P42DaNTvmBmMLM4oL5kL6tVQVo9FfsnJDTqj6VU76whVzjMdMbMa7PV3SHAQuNySan44ToXVFn3gwFmqeDb58t1xqNVAB'
nicehash = False
num_threads = cpu_count()  # Default to number of CPUs

# Fungsi utama untuk koneksi dan login ke pool
def main():
    pool_ip = socket.gethostbyname(pool_host)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((pool_ip, pool_port))
    
    # Shared queue untuk job mining
    job_queue = Queue()

    # Mulai worker sesuai dengan jumlah thread yang ditentukan
    workers = [
        Process(target=worker, args=(job_queue, s))
        for _ in range(num_threads)
    ]
    for w in workers:
        w.start()

    # Persiapkan request login
    login = {
        'method': 'login',
        'params': {
            'login': wallet_address,
            'pass': pool_pass,
            'rigid': '',
            'agent': 'stratum-miner-py/0.1'
        },
        'id': 1
    }
    print(f'Logging into pool: {pool_host}:{pool_port}')
    print(f'Using NiceHash mode: {nicehash}')
    s.sendall((json.dumps(login) + '\n').encode('utf-8'))

    try:
        while True:
            line = s.makefile().readline()
            r = json.loads(line)
            error = r.get('error')
            result = r.get('result')
            method = r.get('method')
            params = r.get('params')

            if error:
                print(f'Error: {error}')
                continue
            if result and result.get('status'):
                print(f'Status: {result.get("status")}')
            if result and result.get('job'):
                login_id = result.get('id')
                job = result.get('job')
                job['login_id'] = login_id
                job_queue.put(job)
            elif method and method == 'job' and len(login_id):
                job_queue.put(params)
    except KeyboardInterrupt:
        print(f'{os.linesep}Exiting')
        for w in workers:
            w.terminate()
        s.close()
        sys.exit(0)


def pack_nonce(blob, nonce):
    b = binascii.unhexlify(blob)
    bin = struct.pack('39B', *bytearray(b[:39]))
    if nicehash:
        bin += struct.pack('I', nonce & 0x00ffffff)[:3]
        bin += struct.pack(f'{len(b)-42}B', *bytearray(b[42:]))
    else:
        bin += struct.pack('I', nonce)
        bin += struct.pack(f'{len(b)-43}B', *bytearray(b[43:]))
    return bin


def worker(job_queue, socket):
    started = time.time()
    hash_count = 0

    while True:
        job = job_queue.get()
        if job.get('login_id'):
            login_id = job.get('login_id')
            print(f'Login ID: {login_id}')

        blob = job.get('blob')
        target = job.get('target')
        job_id = job.get('job_id')
        height = job.get('height')
        block_major = int(blob[:2], 16)
        cnv = 0
        if block_major >= 7:
            cnv = block_major - 6
        if cnv > 5:
            seed_hash = binascii.unhexlify(job.get('seed_hash'))
            print(f'New job with target: {target}, RandomX, height: {height}')
        else:
            print(f'New job with target: {target}, CNv{cnv}, height: {height}')

        target = struct.unpack('I', binascii.unhexlify(target))[0]
        if target >> 32 == 0:
            target = int(0xFFFFFFFFFFFFFFFF / int(0xFFFFFFFF / target))
        nonce = 1

        while True:
            bin = pack_nonce(blob, nonce)
            if cnv > 5:
                hash = pyrx.get_rx_hash(bin, seed_hash, height)
            else:
                hash = pycryptonight.cn_slow_hash(bin, cnv, 0, height)
            hash_count += 1
            hex_hash = binascii.hexlify(hash).decode()
            r64 = struct.unpack('Q', hash[24:])[0]
            if r64 < target:
                elapsed = time.time() - started
                hr = int(hash_count / elapsed)
                print(f'{os.linesep}Hashrate: {hr} H/s')
                if nicehash:
                    nonce = struct.unpack('I', bin[39:43])[0]
                submit = {
                    'method': 'submit',
                    'params': {
                        'id': login_id,
                        'job_id': job_id,
                        'nonce': binascii.hexlify(struct.pack('<I', nonce)).decode(),
                        'result': hex_hash
                    },
                    'id': 1
                }
                print(f'Submitting hash: {hex_hash}')
                socket.sendall((json.dumps(submit) + '\n').encode('utf-8'))
                select.select([socket], [], [], 3)
                if not job_queue.empty():
                    break
            nonce += 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--nicehash', action='store_true', help='NiceHash mode')
    parser.add_argument('--host', action='store', help='Pool host')
    parser.add_argument('--port', action='store', help='Pool port')
    parser.add_argument('--threads', action='store', type=int, default=cpu_count(), help='Number of threads to use')
    args = parser.parse_args()
    
    if args.nicehash:
        nicehash = True
    if args.host:
        pool_host = args.host
    if args.port:
        pool_port = int(args.port)
    if args.threads:
        num_threads = args.threads
    
    main()
