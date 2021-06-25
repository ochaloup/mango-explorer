# 🥭 Mango Explorer

## ⚠ Warning

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.


## ChainKeepers Notes

Have a look into  [Potential bugs](docs/PotentialBugs.md).

Cookbook about how to set-up SOL/USDC and mSOL/USDC marketmaking can be found in [HOWTO](HOWTO.rst).

## ChainKeepers INSTALL

### pre-commit

We use pre-commit to maintain high quality of code we push to master.  We push
everything into master :-)

To set it up, you only need to install pre-commit python suit and install a hook
into your repo clone.  The rest is already setup and commited in master.

To install, issue

  pip install pre-commit
  pre-commit install

Congratulation, you'we made it.


## Introduction

<<<<<<< HEAD
`mango-explorer` provides Python code to interface with [Mango Markets](https://mango.markets), along with a functional [marketmaker]](docs/MarketmakingQuickstart.md).
=======
**I am not yet confident in the figures and calculations. Please don't rely on this code yet!**

This is a project to explore and provide useful code for [Mango Markets](https://mango.markets/).

There are some notebook pages to explore Mango account structures for your own accounts.

There is also a functional liquidator.

The goal is not to be easy to use (although that would be nice!). The goal is to show you how the system works and allow you to use some simeple code to interact with it.


## Running the liquidator

Check out the [Quickstart](Quickstart.md) documentation - it's a walkthrough of setting up and running the liquidator, from creating the account, 'balancing' the wallet across the different tokens, and running the liquidator itself.

It can take around 30 minutes to run through.

Requirements:
* A server with docker installed
* Some SOL to pay for transactions
* Some USDT to fund the liquidation wallet


## Running the notebooks
>>>>>>> 71149f7 (First cut at a lot of V3 code.)

Here's a brief but complete example of how to place and cancel an order. [This example is runnable in your browser](https://mybinder.org/v2/gh/blockworks-foundation/mango-explorer-examples/HEAD?labpath=PlaceAndCancelOrders.ipynb)!

```
import decimal
import mango
import os
import time

# Load the wallet from the environment variable 'KEYPAIR'. (Other mechanisms are available.)
wallet = mango.Wallet(os.environ.get("KEYPAIR"))

# Create a 'devnet' Context
context = mango.ContextBuilder.build(cluster_name="devnet")

<<<<<<< HEAD
# Load the wallet's account
group = mango.Group.load(context)
accounts = mango.Account.load_all_for_owner(context, wallet.address, group)
account = accounts[0]

# Load the market
stub = context.market_lookup.find_by_symbol("SOL-PERP")
market = mango.ensure_market_loaded(context, stub)
=======
>>>>>>> 71149f7 (First cut at a lot of V3 code.)

market_operations = mango.create_market_operations(context, wallet, account, market, dry_run=False)

print("Orders (initial):")
for order in market_operations.load_orders():
    print(order)

# Go on - try to buy 1 SOL for $10.
order = mango.Order.from_basic_info(side=mango.Side.BUY,
                                    price=decimal.Decimal(10),
                                    quantity=decimal.Decimal(1),
                                    order_type=mango.OrderType.POST_ONLY)
placed_order = market_operations.place_order(order)
print("\n\nplaced_order\n\t", placed_order)

print("\n\nSleeping for 10 seconds...")
time.sleep(10)

<<<<<<< HEAD
print("\n\nOrders (including our new order):")
for order in market_operations.load_orders():
    print(order)
=======
To try this out, go to the [Show All Margin Accounts](ShowAllMarginAccounts.ipynb) page and run the code.


## Show details of the current Mango gorup

You can use the [Show Group](ShowGroup.ipynb) page to inspect the details of the current Mango group.
>>>>>>> 71149f7 (First cut at a lot of V3 code.)

cancellaton_signatures = market_operations.cancel_order(placed_order)
print("\n\ncancellaton_signatures:\n\t", cancellaton_signatures)

print("\n\nSleeping for 10 seconds...")
time.sleep(10)

print("\n\nOrders (without our order):")
for order in market_operations.load_orders():
    print(order)

```

Many more examples are provided in a separate [Github repo](https://github.com/blockworks-foundation/mango-explorer-examples) and can be [run in your browser (no installation required!) at Binder](https://mybinder.org/v2/gh/blockworks-foundation/mango-explorer-examples/HEAD).


<<<<<<< HEAD
## Running the marketmaker

There is a [Marketmaking Quickstart](docs/MarketmakingQuickstart.md) - a walkthrough of setting up and running the marketmaker on devnet, from setting up the account, depositing tokens, to running the marketmaker itself.

It can take around 30 minutes to run through.

Requirements:
* A server with docker installed

**Note** This walkthrough is devnet-only so no actual funds are used or at-risk.

=======
>>>>>>> 71149f7 (First cut at a lot of V3 code.)
## References

* [SolanaPy](https://github.com/michaelhly/solana-py/)
* [PySerum](https://github.com/serum-community/pyserum/)
* [Python Decimal Class](https://docs.python.org/3/library/decimal.html)
* [Python Construct Library](https://construct.readthedocs.io/en/latest/)
* [Python Observables](https://rxpy.readthedocs.io/en/latest/)
* [RxPy Backpressure](https://github.com/daliclass/rxpy-backpressure)
<<<<<<< HEAD
=======
* [Pyston](https://www.pyston.org/)
* [Flux Aggregator](https://github.com/octopus-network/solana-flux-aggregator)
>>>>>>> 71149f7 (First cut at a lot of V3 code.)


# Support

[🥭 Mango Markets](https://mango.markets/) support is available at: [Docs](https://docs.mango.markets/) | [Discord](https://discord.gg/67jySBhxrg) | [Twitter](https://twitter.com/mangomarkets) | [Github](https://github.com/blockworks-foundation) | [Email](mailto:hello@blockworks.foundation)