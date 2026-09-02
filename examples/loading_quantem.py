"""
Loading Data into the quantem Package
=====================================

This example demonstrates how to load data into the quantem package.
"""

from quantem.core.io.file_readers import read_4dstem

from emdatabase.data import BilayerWS2

# Ensure the dataset is downloaded
dataset = BilayerWS2()
file_path = dataset.download()
# Load the data using quantem
data = read_4dstem(file_path)
print(data)
# %%
# Display the data using quantem's built-in visualization
data.show()
