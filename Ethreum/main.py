import os
import time
from dotenv import load_dotenv
from web3 import Web3 
load_dotenv()
RPC_URL = os.getenv("RPC_URL")
if not RPC_URL:
    raise SystemExit()
w3 = Web3(Web3.HTTPProvider(RPC_URL))
ADDRESS = os.getenv("CHECK_ADDRESS","0x000000000000000000000000000000000000000000")

def to_checksum(addr: str) -> str:
    return w3.to_checksum_address(addr)

def main():
    print("Работает")

    connected = w3.is_connected()
    print("Connected:", connected)

    chain_id = w3.eth.chain_id
    print("Chain ID:", chain_id)

    block_number = w3.eth.block_number
    print("Block:", block_number)

    addr = to_checksum(ADDRESS)
    balance_wei = w3.eth.get_balance(addr)
    balance_eth = w3.from_wei(balance_wei,"ether")
    print("Address:", addr)
    print("Balance:", balance_eth)

    gas_price_wei = w3.eth.gas_price
    gas_gwei = w3.from_wei(gas_price_wei, "gwei")
    print("Gas price (GWEI):", gas_gwei)

if __name__ == "__main__":
    main()
while True:
    current_block = w3.eth.block_number
    print("New block:", current_block)
    time.sleep(5)  
    