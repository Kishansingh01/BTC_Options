from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np


def generate_straddle_payoff_chart(
    strike: float = 85000.0,
    combined_premium: float = 3400.0,
    stop_loss_pct: float = 0.01,
    take_profit_pct: float = 0.02,
    save_path: str = "straddle_payoff.png",
):
    """
    Generate an institutional payoff and risk profile visualization for the BTC Short Straddle.
    """
    lower_range = strike - (combined_premium * 3)
    upper_range = strike + (combined_premium * 3)
    spot_prices = np.linspace(lower_range, upper_range, 500)

    # Short Call Payoff: Premium - max(S - K, 0)
    # Short Put Payoff:  Premium - max(K - S, 0)
    call_payoffs = (combined_premium / 2) - np.maximum(spot_prices - strike, 0)
    put_payoffs = (combined_premium / 2) - np.maximum(strike - spot_prices, 0)
    total_payoff = call_payoffs + put_payoffs

    # Breakevens
    upper_be = strike + combined_premium
    lower_be = strike - combined_premium

    plt.figure(figsize=(10, 6), dpi=150)
    plt.plot(spot_prices, total_payoff, label="Combined Short Straddle Payoff", color="#2563EB", linewidth=2.5)
    plt.axhline(0, color="gray", linestyle="--", alpha=0.7)
    plt.axvline(strike, color="#10B981", linestyle=":", label=f"ATM Strike (${strike:,.0f})")

    # Mark Breakevens
    plt.axvline(lower_be, color="#EF4444", linestyle="--", label=f"Lower BE (${lower_be:,.0f})")
    plt.axvline(upper_be, color="#EF4444", linestyle="--", label=f"Upper BE (${upper_be:,.0f})")

    # Profit zone fill
    plt.fill_between(spot_prices, total_payoff, 0, where=(total_payoff > 0), color="#10B981", alpha=0.15, label="Profit Zone")
    plt.fill_between(spot_prices, total_payoff, 0, where=(total_payoff < 0), color="#EF4444", alpha=0.15, label="Loss Zone")

    plt.title("BTC Short Straddle Payoff Structure & Risk Envelope", fontsize=14, fontweight="bold")
    plt.xlabel("BTC Spot Price at Expiry ($)", fontsize=11)
    plt.ylabel("PnL per Contract ($)", fontsize=11)
    plt.grid(True, alpha=0.3)
    plt.legend(loc="upper right", framealpha=0.9)
    plt.tight_layout()

    plt.savefig(save_path)
    plt.close()
    print(f"Payoff diagram successfully generated and saved to: {save_path}")


def print_risk_profile(strike: float = 85000.0, combined_premium: float = 3400.0, sl_pct: float = 0.01, tp_pct: float = 0.02):
    upper_be = strike + combined_premium
    lower_be = strike - combined_premium
    max_profit = combined_premium
    sl_trigger = combined_premium * (1 + sl_pct)
    tp_trigger = combined_premium * (1 - tp_pct)

    print("\n" + "=" * 65)
    print("BTC SHORT STRADDLE RISK PROFILE & GREEKS ANALYSIS")
    print("=" * 65)
    print(f"  ATM Strike Price:        ${strike:,.2f}")
    print(f"  Combined Entry Premium:  ${combined_premium:,.2f}")
    print(f"  Max Theoretical Profit:  ${max_profit:,.2f} (at exact strike)")
    print(f"  Lower Breakeven (at exp):${lower_be:,.2f}")
    print(f"  Upper Breakeven (at exp):${upper_be:,.2f}")
    print("-" * 65)
    print(f"  Level 2 Risk Rules:")
    print(f"  -> Stop-Loss (+{sl_pct*100:.1f}% buyback):   >= ${sl_trigger:,.2f} (Max Loss: ${sl_trigger - combined_premium:,.2f})")
    print(f"  -> Take-Profit (-{tp_pct*100:.1f}% buyback): <= ${tp_trigger:,.2f} (Locked Gain: ${combined_premium - tp_trigger:,.2f})")
    print("-" * 65)
    print("  Greeks Characteristics:")
    print("  * Delta (Δ):  ~0.00 (Market-neutral at entry)")
    print("  * Gamma (Γ):  Negative (Suffers from large directional swings)")
    print("  * Theta (Θ):  Positive (Collects time decay every passing minute)")
    print("  * Vega (ν):   Negative (Profits when implied volatility drops)")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    print_risk_profile()
    generate_straddle_payoff_chart()

