"""
Calculates simple combinations of prices.
"""
from typing import Dict, List, Tuple


class PortfolioState:
    """
    Stores information about current portfolio and optimal portfolio.
    """

    def __init__(
        self,
        instruments: List[str],
        model_cfg,  # FIXME: add type, when this class gets used
        update_type: str
    ) -> None:
        self.optimal_portfolio: Dict[str, float] = {
            currency_name: weight
            for currency_name, weight in model_cfg.optimal_portfolio_weights.items()
        }
        self.current_portfolio: Dict[str, float] = {
            currency_name: float('NaN')
            for currency_name in model_cfg.optimal_portfolio_weights.keys()
        }

        if update_type not in {'api', 'websocket'}:
            raise ValueError(f'Incorrect update_type {update_type}')
        self.update_type = update_type

    def speed_of_convergence(self) -> Dict[str, float]:
        """
        Per instrument gives a speed of how fast we want increase weight
        of given instrument in a portoflio.

        This happens by using output of this method to adjust the fair price

        For a portfolio of SOL, mSOL, USDC, lets say we have output
            {SOL: 1.01, mSOL: 0.99, USDC: 1}
        This mean that we want to increase the size of SOL (we want to decrease
        price of SOL in portfolio), vice versa for mSOL (decrease size of mSOL)
        and keep steady the USDC.

        FIXME: this below, belongs somewhere else
        Lets say we have fair prices
        mSOL/SOL = 1
        mSOL/USDC = 150
        SOL/USDC = 150
        the adjusted fair price is
        mSOL/SOL = 1 * 1/speed['mSOL'] * speed['SOL'] = 1 * 1/0.99 * 1.01 = 1.020...
        mSOL/USDC = 150 * 1/speed['mSOL'] * speed['USDC'] = 150 * 1/0.99 * 1 = 151.51...
        SOL/USDC = 150 * 1/speed['SOL'] * speed['USDC'] = 150 * 1/1.01 * 1 = 148.51...
        """
        return {
            'mSOL': 1,
            'SOL': 1
        }

    def get_portfolio_adjusted_price(
        self,
        instruments: Tuple[str, str],
        fair_price: float
    ) -> float:
        speed_of_convergence = self.speed_of_convergence()
        speed_of_convergence_0 = speed_of_convergence[instruments[0]]
        speed_of_convergence_1 = speed_of_convergence[instruments[1]]
        return fair_price / speed_of_convergence_0 * speed_of_convergence_1

    def update(self) -> None:
        if self.update_type == 'api':
            self.update_by_api()
        else:
            # FIXME: drop this section of if-else later down the line
            pass

    def update_by_api(self) -> None:
        """Updates current_portfolio by requests to api."""
        raise NotImplementedError

    def update_by_websocket(self) -> None:
        """Updates current portfolio through websocket"""
        raise NotImplementedError
