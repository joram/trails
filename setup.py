import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="trails",
    version="0.0.4",
    author="John Oram",
    author_email="john@oram.ca",
    description="A small package of hiking and mountaineering trails",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/joram/trails",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    packages=["trails"],
    package_dir={
        "trails": "trails",
    },
    package_data={
        'trails': ['data/*'],
    },
    python_requires=">=3.6",
    install_requires=[
        "gpxpy",
        "geojson",
    ],
)
