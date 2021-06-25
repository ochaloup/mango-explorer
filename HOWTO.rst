Solana
======

1. install solana

https://docs.solana.com/cli/install-solana-cli-tools


COPE/USDC on Mango
==================

1. Create a key in Phantom

2. Deposit 1 SOL to the address

3. Export private key

4. Set the key in you environment

      export KEY=the key exported from Phantom
    export SECRET_KEY=`./bin/recode-key`

ensure, you don't save the key in you history, issue

    history -c

or ensure that the space at the start of the command line prevents bash from
saving it in you history.

5. Create the Mango account

   ./bin/ensure-account

6. Create the Mango open orders account

   ./bin/ensure-open-orders --market COPE/USDC

The script knows, we want to create Mango open orders, because the market exists
on Mango.  If it does not, it would create Serum open orders.

7. Deposit something to trade with, possibly USDC

Use the GUI for this.

8. Setup you trader and start trading


mSOL/USDC on Serum
==================

1. Create wallet, or using Phantom

   solana-keygen

2. copy private key as above or from Pahntom using

https://stackoverflow.com/questions/69245982/import-phantom-wallet-private-key-into-solana-cli

    import base58
    byte_array = base58.b58decode(MY_PRIVATE_KEY_IN_BASE58)
    json_string = "[" + ",".join(map(lambda b: str(b), byte_array)) + "]"
    print(json_string)

Or use `bin/recode-key`

3. Update and modify symbols .json

https://github.com/solana-labs/token-list/tree/main/src/tokens

   1b2f265 Update solana.tokenlist.json

4. Create mSOL and USDC associated token account

    export CLUSTER_URL=https://falling-aged-flower.solana-mainnet.quiknode.pro/63ca6516821bd013d3d4cd28a1e872509af0d14b/
    ./bin/create-associated-token-account --symbol mSOL

    Associated token account created at: A2PuNdL1YjwYzu3Cix7BK5xfiKLuJLoJh3S38z8Pz38W.

    ./bin/ensure-associated-token-account --symbol USDC

    Associated token account created at: A2fW9Cv3qvererFPtHVzdcVM2RfiMZ8FYzvHhDQEb4VJ.

5. Prepare Serum OpenOrders account

There is no need to prepare any special Serum account.  The associated token
accounts were created above.  Serum needs, however (as does Mango), an
"OpenOrders account" to be created.  Otherwise, settling orders does not work!

   ./bin/ensure-open-orders  --market MSOL/USDC

   OpenOrders account for MSOL/USDC is BzJSqypgcCz9QJmEQErWB6r1c4yFe4ZNbjjL8dBBXshU

6. To quote mSOL/SOL, create SOL account

    ./bin/ensure-associated-token-account --symbol SOL

    Associated token account created at: ExsW3u6QWjbgELnZia8TU6ZNK7V5Pkm3JwnzHW1GGx4f.
