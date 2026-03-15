from __future__ import annotations

from dotenv import load_dotenv
import os

load_dotenv()

RPC_URL = os.getenv("RPC_URL")
print(RPC_URL)

import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.exceptions import Web3RPCError


def env_flag(name: str, default: bool = False) -> bool:
	value = os.getenv(name)
	if value is None:
		return default
	return value.strip().lower() in {"1", "true", "yes", "on"}


def to_wei_from_env(name: str, default_eth: str) -> int:
	raw = os.getenv(name, default_eth).strip()
	try:
		return Web3.to_wei(Decimal(raw), "ether")
	except (InvalidOperation, ValueError) as exc:
		raise ValueError(f"{name} must be a valid ETH amount, got: {raw}") from exc


def upsert_env_values(env_path: Path, values: dict[str, str]) -> None:
	env_path.parent.mkdir(parents=True, exist_ok=True)
	if env_path.exists():
		lines = env_path.read_text(encoding="utf-8").splitlines()
	else:
		lines = []

	remaining = dict(values)
	updated_lines: list[str] = []
	for line in lines:
		stripped = line.strip()
		if not stripped or stripped.startswith("#") or "=" not in line:
			updated_lines.append(line)
			continue

		key, _, _ = line.partition("=")
		key = key.strip()
		if key in remaining:
			updated_lines.append(f"{key}={remaining.pop(key)}")
		else:
			updated_lines.append(line)

	for key, value in remaining.items():
		updated_lines.append(f"{key}={value}")

	env_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def get_or_create_wallet(env_path: Path) -> tuple[LocalAccount, bool]:
	private_key = os.getenv("PRIVATE_KEY", "").strip()
	wallet_address = os.getenv("WALLET_ADDRESS", "").strip()

	if private_key and wallet_address:
		account = Account.from_key(private_key)
		if account.address.lower() != wallet_address.lower():
			print("⚠️ WALLET_ADDRESS не совпадает с PRIVATE_KEY, обновляю WALLET_ADDRESS в .env.")
			upsert_env_values(env_path, {"WALLET_ADDRESS": account.address})
		return account, False

	new_account = Account.create()
	upsert_env_values(
		env_path,
		{
			"PRIVATE_KEY": new_account.key.hex(),
			"WALLET_ADDRESS": new_account.address,
		},
	)
	return new_account, True


def get_fee_params(w3: Web3) -> dict[str, int]:
	latest_block = w3.eth.get_block("latest")
	base_fee = latest_block.get("baseFeePerGas")

	if base_fee is None:
		gas_price = w3.eth.gas_price
		return {"gasPrice": gas_price}

	priority_fee = w3.eth.max_priority_fee
	max_fee = base_fee * 2 + priority_fee
	return {
		"maxPriorityFeePerGas": priority_fee,
		"maxFeePerGas": max_fee,
	}


def print_section(title: str) -> None:
	print("\n" + "=" * 72)
	print(f"🔷 {title.upper()}")
	print("=" * 72)


def main() -> None:
	env_path = Path(__file__).with_name(".env")
	load_dotenv(dotenv_path=env_path)

	rpc_url = os.getenv("RPC_URL", "").strip()
	if not rpc_url:
		print("❌ ПЕРЕМЕННАЯ RPC_URL НЕ НАЙДЕНА В ФАЙЛЕ .ENV")
		sys.exit(1)

	print_section("ШАГ 1 / ПРОВЕРКА КОШЕЛЬКА В .ENV")
	sender, created_now = get_or_create_wallet(env_path)
	if created_now:
		print("✅ СГЕНЕРИРОВАН НОВЫЙ КОШЕЛЕК И СОХРАНЕН В .ENV:")
		print(f"PRIVATE_KEY={sender.key.hex()}")
		print(f"WALLET_ADDRESS={sender.address}")
		print("\n⛔ СКРИПТ ОСТАНОВЛЕН СПЕЦИАЛЬНО НА ЭТОМ ШАГЕ.")
		print("➡️ ПОПОЛНИ WALLET_ADDRESS ЧЕРЕЗ SEPOLIA FAUCET И ЗАПУСТИ СНОВА.")
		sys.exit(0)

	print(f"✅ НАЙДЕН СУЩЕСТВУЮЩИЙ КОШЕЛЕК: {sender.address}")
	print("▶️ ПРОДОЛЖАЮ ВЫПОЛНЕНИЕ СЦЕНАРИЯ С ЭТИМ АДРЕСОМ.")

	print_section("ШАГ 2 / ПОДКЛЮЧЕНИЕ К SEPOLIA ПО RPC")
	w3 = Web3(Web3.HTTPProvider(rpc_url))
	if not w3.is_connected():
		print("❌ НЕ УДАЛОСЬ ПОДКЛЮЧИТЬСЯ К RPC")
		print(f"RPC_URL: {rpc_url}")
		print("ПРОВЕРЬ ИНТЕРНЕТ, ДОСТУПНОСТЬ ENDPOINT И КОРРЕКТНОСТЬ RPC-КЛЮЧА.")
		sys.exit(1)

	chain_id = w3.eth.chain_id
	latest_block = w3.eth.block_number
	print(f"ПОДКЛЮЧЕНИЕ: ДА")
	print(f"CHAIN ID:  {chain_id}")
	print(f"БЛОК:      {latest_block}")

	print_section("ШАГ 3 / ПОЛУЧЕНИЕ NONCE")
	nonce = w3.eth.get_transaction_count(sender.address, "pending")
	print(f"NONCE ДЛЯ АДРЕСА {sender.address}: {nonce}")

	to_address = os.getenv("TO_ADDRESS", "").strip()
	if not to_address:
		to_address = sender.address

	if not Web3.is_address(to_address):
		print(f"❌ НЕКОРРЕКТНЫЙ TO_ADDRESS: {to_address}")
		sys.exit(1)

	amount_wei = to_wei_from_env("AMOUNT_ETH", "0.00001")
	to_checksum = Web3.to_checksum_address(to_address)

	print_section("ШАГ 4 / ФОРМИРОВАНИЕ ТРАНЗАКЦИИ")
	tx_base = {
		"chainId": chain_id,
		"nonce": nonce,
		"from": sender.address,
		"to": to_checksum,
		"value": amount_wei,
	}

	gas_limit = int(os.getenv("GAS_LIMIT", "21000"))
	estimate_enabled = env_flag("ESTIMATE_GAS", default=True)
	if estimate_enabled:
		try:
			estimated = w3.eth.estimate_gas(tx_base)
			gas_limit = max(gas_limit, estimated)
		except Exception:
			pass

	fee_params = get_fee_params(w3)
	tx = {
		**tx_base,
		"gas": gas_limit,
		**fee_params,
	}
	print("ПАРАМЕТРЫ ТРАНЗАКЦИИ:")
	print(tx)

	sender_balance = w3.eth.get_balance(sender.address)
	if "maxFeePerGas" in tx:
		max_possible_fee = tx["gas"] * tx["maxFeePerGas"]
	else:
		max_possible_fee = tx["gas"] * tx["gasPrice"]
	max_total_cost = tx["value"] + max_possible_fee

	print_section("ПРЕДПРОВЕРКА БАЛАНСА")
	print(f"БАЛАНС ОТПРАВИТЕЛЯ (WEI): {sender_balance}")
	print(f"МАКСИМАЛЬНАЯ СТОИМОСТЬ TX (WEI): {max_total_cost}")

	if sender_balance < max_total_cost:
		print("❌ НЕДОСТАТОЧНО СРЕДСТВ ДЛЯ ОТПРАВКИ ТРАНЗАКЦИИ.")
		print("НУЖНО ПОПОЛНИТЬ WALLET_ADDRESS ТЕСТОВЫМ SEPOLIA ETH ЧЕРЕЗ FAUCET.")
		sys.exit(1)

	print_section("ШАГ 5 / ПОДПИСЬ ТРАНЗАКЦИИ")
	signed = w3.eth.account.sign_transaction(tx, sender.key)
	raw_hex = signed.raw_transaction.hex()
	print(f"ДЛИНА RAW TRANSACTION: {len(raw_hex)} HEX-СИМВОЛОВ")
	print(f"TX HASH ДО ОТПРАВКИ: {signed.hash.hex()}")

	print_section("ШАГ 6 / ОТПРАВКА В СЕТЬ")
	try:
		tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
	except Web3RPCError as exc:
		print(f"❌ RPC ОШИБКА ПРИ ОТПРАВКЕ ТРАНЗАКЦИИ: {exc}")
		sys.exit(1)
	tx_hash_hex = tx_hash.hex()
	print(f"TX HASH ПОСЛЕ ОТПРАВКИ: {tx_hash_hex}")
	print(f"ССЫЛКА НА SEPOLIA EXPLORER: https://sepolia.etherscan.io/tx/{tx_hash_hex}")
	print("ПЕРВЫЙ СТАТУС ОБЫЧНО PENDING (ТРАНЗАКЦИЯ В MEMPOOL).")

	print_section("ШАГ 7 / ОЖИДАНИЕ ВКЛЮЧЕНИЯ В БЛОК")
	timeout_sec = int(os.getenv("RECEIPT_TIMEOUT_SEC", "180"))
	receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout_sec)
	current_block = w3.eth.block_number
	confirmations = max(0, current_block - receipt.blockNumber + 1)
	status_text = "success" if receipt.status == 1 else "failed"

	print(f"ВКЛЮЧЕНА В БЛОК:  {receipt.blockNumber}")
	print(f"ПОДТВЕРЖДЕНИЯ:    {confirmations}")
	print(f"ИЗРАСХОДОВАНО GAS: {receipt.gasUsed}")
	print(f"ИТОГОВЫЙ СТАТУС:  {status_text.upper()}")

	print_section("ИТОГ УРОКА")
	print("1) ТРАНЗАКЦИЯ = СТРУКТУРА ДАННЫХ.")
	print("2) ПОДПИСЬ = ДОКАЗАТЕЛЬСТВО ВЛАДЕНИЯ ПРИВАТНЫМ КЛЮЧОМ.")
	print("3) ВКЛЮЧЕНИЕ В БЛОК = ИЗМЕНЕНИЕ ГЛОБАЛЬНОГО СОСТОЯНИЯ СЕТИ.")


if __name__ == "__main__":
	main()
