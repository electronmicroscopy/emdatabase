"""
Loading Data with HyperSpy
===========================

This example demonstrates how to load and visualize data using the HyperSpy library.
"""

import hyperspy.api as hs

from emdatabase.data import BilayerWS2

# Load a dataset using HyperSpy
dataset = BilayerWS2()
data_path = dataset.download()  # Download the dataset if not already available
data = hs.load(data_path)
data

# %%
# Display the dataset
data.plot()
