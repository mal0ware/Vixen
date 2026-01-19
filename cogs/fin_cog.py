import os
import json
import random

import discord
import requests
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

from discord.ui import View, Button
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv


class finCog(commands.Cog):
    """
    Cog providing simple financial analysis commands using yfinance data.
    
    Exposes:
    - /rsi (or !rsi)            : download OHLC data, compute RSI + MAs,
                                  plot price + MAs + RSI and show table with RSI
    - /moving_average (or !...) : download OHLC data, compute and plot moving
                                  averages and show table without RSI

    Other files are expected to only load this Cog; public command names
    (rsi, moving_average) and their signatures must stay stable.
    """

    def __init__(self, bot: commands.Bot):
        # Keep bot reference for potential future use
        self.bot = bot

    # --------------------------------------------------------------------- #
    # Helper methods (not commands)
    # --------------------------------------------------------------------- #

    def compute_rsi(self, data: pd.DataFrame, window: int = 14) -> pd.DataFrame:
        """
        Compute the Relative Strength Index (RSI) for a price DataFrame.

        Expects:
          - data: DataFrame containing a 'Close' column.
          - window: RSI period, typically 14.

        Returns:
          The same DataFrame with an added 'RSI' column.
        """
        # Price change between consecutive rows
        delta = data["Close"].diff()

        # Separate gains and losses
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        # Rolling averages of gains and losses
        avg_gain = gain.rolling(window=window, min_periods=window).mean()
        avg_loss = loss.rolling(window=window, min_periods=window).mean()

        # Relative strength (RS) and RSI calculation
        rs = avg_gain / avg_loss
        data["RSI"] = 100 - (100 / (1 + rs))

        return data

    def _download_price_data(
        self,
        ticker: str,
        start: str = "2025-01-01",
        end: str = "2025-10-01",
    ) -> pd.DataFrame:
        """
        Small wrapper around yfinance.download for consistency and future changes.

        Returns:
          DataFrame with OHLCV data. May be empty if ticker is invalid.
        """
        return yf.download(ticker, start=start, end=end)

    def _prepare_output_path(self, user_id: int) -> str:
        """
        Create and return the output path for plots for a specific user.
        File name is kept as 'savings_boxplot.png' to preserve external expectations.
        """
        output_dir = f"temp/{user_id}"
        os.makedirs(output_dir, exist_ok=True)
        return os.path.join(output_dir, "savings_boxplot.png")

    def _finalize_plot(self, save_path: str) -> None:
        """
        Save the current matplotlib figure and clear it to avoid overlaps
        between different command invocations.
        """
        plt.tight_layout()
        plt.savefig(save_path)
        plt.clf()

    def _send_dataframe_preview(
        self,
        df: pd.DataFrame,
        columns: list[str],
        rows: int = 10,
    ) -> str:
        """
        Prepare a small, text-based preview of the DataFrame for Discord.

        Arguments:
          - df: DataFrame with data.
          - columns: List of columns to include in the preview.
          - rows: Number of rows from the end of the DataFrame to show.

        Returns:
          A string formatted as a code block for Discord.
        """
        # Take the last N rows of the selected columns to keep it short
        preview = df[columns].tail(rows)

        # Round numeric values for readability
        preview = preview.round(2)

        # Convert to plain text table
        table_str = preview.to_string()

        # Wrap as a Discord code block
        return f"```{table_str}```"

    # --------------------------------------------------------------------- #
    # Commands
    # --------------------------------------------------------------------- #

    @commands.hybrid_command(help="Analyze a ticker using RSI and moving averages")
    @commands.cooldown(1, 15, commands.BucketType.guild)
    @app_commands.describe(
        ticker="The ticker to analyze (e.g. AAPL, MSFT, SPY).",
    )
    async def rsi(self, ctx: commands.Context, ticker: str):
        """
        Hybrid command:
          - Downloads price data for the given ticker.
          - Computes 20-day and 50-day moving averages.
          - Computes RSI using compute_rsi().
          - Plots Close, MA20, MA50 on the top axis and RSI on the bottom axis.
          - Sends the plot image.
          - Sends a text preview of the last rows of the DataFrame including RSI.

        This makes the RSI command visually and textually distinct from the
        moving_average command.
        """
        data = self._download_price_data(ticker)

        # Basic sanity check: empty data usually means invalid ticker or no data
        if data.empty:
            await ctx.reply(f"Failed to download data for ticker `{ticker}`.")
            return

        # Compute moving averages for plotting
        data["MA20"] = data["Close"].rolling(window=20, min_periods=1).mean()
        data["MA50"] = data["Close"].rolling(window=50, min_periods=1).mean()

        # Compute RSI and keep it in the DataFrame
        data = self.compute_rsi(data)

        # Create a 2-row figure: price + MAs on top, RSI on bottom
        fig, (ax_price, ax_rsi) = plt.subplots(
            2, 1, figsize=(10, 8), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
        )

        # Top subplot: close price and moving averages
        ax_price.plot(data.index, data["Close"], label="Close")
        ax_price.plot(data.index, data["MA20"], label="MA20")
        ax_price.plot(data.index, data["MA50"], label="MA50")
        ax_price.set_ylabel("Price")
        ax_price.legend(loc="upper left")
        ax_price.set_title(f"{ticker} Price with MA20 / MA50")

        # Bottom subplot: RSI
        ax_rsi.plot(data.index, data["RSI"], label="RSI")
        ax_rsi.axhline(70, linestyle="--")  # typical overbought level
        ax_rsi.axhline(30, linestyle="--")  # typical oversold level
        ax_rsi.set_ylabel("RSI")
        ax_rsi.set_xlabel("Date")
        ax_rsi.legend(loc="upper left")

        save_path = self._prepare_output_path(ctx.author.id)
        self._finalize_plot(save_path)

        # Send the plot
        await ctx.channel.send(
            content=f"Your RSI + MA analysis for `{ticker}`:",
            file=discord.File(save_path),
        )

        # Send a dataframe preview including RSI so you can see the numbers directly
        preview_text = self._send_dataframe_preview(
            data,
            columns=["Close", "MA20", "MA50", "RSI"],
            rows=10,
        )
        await ctx.channel.send(content=f"Last rows (with RSI) for `{ticker}`:\n{preview_text}")

    @commands.hybrid_command(help="Analyze a ticker using moving averages only")
    @commands.cooldown(1, 15, commands.BucketType.guild)
    @app_commands.describe(
        ticker="The ticker to analyze (e.g. AAPL, MSFT, SPY).",
    )
    async def moving_average(self, ctx: commands.Context, ticker: str):
        """
        Hybrid command:
          - Downloads price data for the given ticker.
          - Computes 20-day and 50-day moving averages.
          - Plots Close, MA20, MA50 on a single chart and sends it as an image.
          - Sends a text preview of the last rows of the DataFrame with just
            price and moving averages (no RSI column).

        This produces a different visual and textual output from the RSI command.
        """
        data = self._download_price_data(ticker)

        if data.empty:
            await ctx.reply(f"Failed to download data for ticker `{ticker}`.")
            return

        # Calculate short-term and long-term moving averages
        data["MA20"] = data["Close"].rolling(window=20, min_periods=1).mean()
        data["MA50"] = data["Close"].rolling(window=50, min_periods=1).mean()

        # Plot price and moving averages
        plt.figure(figsize=(10, 6))
        plt.plot(data.index, data["Close"], label="Close")
        plt.plot(data.index, data["MA20"], label="MA20")
        plt.plot(data.index, data["MA50"], label="MA50")
        plt.ylabel("Price")
        plt.xlabel("Date")
        plt.title(f"{ticker} Price with MA20 / MA50")
        plt.legend(loc="upper left")

        save_path = self._prepare_output_path(ctx.author.id)
        self._finalize_plot(save_path)

        # Send the plot
        await ctx.channel.send(
            content=f"Your moving average analysis for `{ticker}`:",
            file=discord.File(save_path),
        )

        # Send a dataframe preview without RSI (to distinguish from rsi command)
        preview_text = self._send_dataframe_preview(
            data,
            columns=["Close", "MA20", "MA50"],
            rows=10,
        )
        await ctx.channel.send(content=f"Last rows (MAs only) for `{ticker}`:\n{preview_text}")


async def setup(bot: commands.Bot):
    """
    Standard async setup function used by discord.py to load the Cog.
    Other files are expected to call bot.load_extension(...) which will
    invoke this function.
    """
    await bot.add_cog(finCog(bot))
