# # ⚠ Warning
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
# LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN
# NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
# [🥭 Mango Markets](https://mango.markets/) support is available at:
#   [Docs](https://docs.mango.markets/)
#   [Discord](https://discord.gg/67jySBhxrg)
#   [Twitter](https://twitter.com/mangomarkets)
#   [Github](https://github.com/blockworks-foundation)
#   [Email](mailto:hello@blockworks.foundation)

from .context import Context
from .contextbuilder import ContextBuilder
from .oracle import OracleProvider
from .oracles.ftx import ftx, ftx_mango
from .oracles.market import market
from .oracles.pythnetwork import pythnetwork
from .oracles.stub import stub
from .oracles.msol import MSolOracleProvider
from .oracles.binance import binance
from .oracles.kraken import kraken
from mango.types_ import Configuration



# # 🥭 Oracle Factory
#
# This file allows you to create a concreate OracleProvider for a specified provider name.
#
def create_oracle_provider(context: Context, provider_name: str,
                           cfg: Configuration # CHKP addition
                           ) -> OracleProvider:
    proper_provider_name: str = provider_name.upper()
    if proper_provider_name == "FTX_MANGO":
        return ftx_mango.FtxOracleProvider()
    elif proper_provider_name == "MARKET":
        return market.MarketOracleProvider()
    elif proper_provider_name == "PYTH":
        return pythnetwork.PythOracleProvider(context, cfg)
    elif proper_provider_name == "PYTH-MAINNET":
        mainnet_beta_pyth_context: Context = ContextBuilder.forced_to_mainnet_beta(context)
        return pythnetwork.PythOracleProvider(mainnet_beta_pyth_context, cfg)
    elif proper_provider_name == "PYTH-DEVNET":
        devnet_pyth_context: Context = ContextBuilder.forced_to_devnet(context)
        return pythnetwork.PythOracleProvider(devnet_pyth_context, cfg)
    elif proper_provider_name == "STUB":
        return stub.StubOracleProvider()
    elif proper_provider_name == "FTX":
        return ftx.FtxOracleProvider(cfg)
    elif proper_provider_name == "MSOL":
        return MSolOracleProvider(cfg)
    elif proper_provider_name == "BINANCE":
        return binance.BinanceOracleProvider(cfg)
    elif proper_provider_name == "KRAKEN":
        return kraken.KrakenOracleProvider(cfg)
    raise Exception(f"Unknown oracle provider '{proper_provider_name}'.")
