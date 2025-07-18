# aries-bench
aries-bench is a set of scripts to evaluate aries performance on minizinc problems. It allows to easily compile and solve several problems with different solver configurations. Finally a python script allows to visualize the results to compare the performance.

Remark: for now the system only works for optimization problems.

Titouan Seraud - [titouan.seraud@laas.fr](mailto:titouan.seraud\@laas.fr) <!-- titouan.seraud@insa-toulouse.fr -->

<details>
<summary><b>Table of contents</b></summary>

- [Installation](#installation)
- [Usage](#usage)
- [Reference](#reference)
- [Documentation](#documentation)
- [Perspectives](#perspectives)
- [Useful links](#useful-links)
</details>


## Installation

### Just
Make sure you have installed [just](https://github.com/casey/just?tab=readme-ov-file#installation). While this tool is not strictly mandatory we will assume you have it for all the following commands.

### Aries
Make sure `aries` command is available and associated to aries flatzinc solver. If it is not the case, please add it to the `PATH`.
```
export PATH=/path/to/aries/flatzinc/solver:$PATH
```

### Minizinc
Make sure you have installed [minizinc](https://www.minizinc.org/). Verify aries is correctly referenced in `MZN_SOLVER_PATH`. If it is not present, you can add it using the following command.
```bash
export MZN_SOLVER_PATH=/path/to/aries/flatzinc/solver/share
```

### Python
Make sure you have a recent python version. I used version 3.10 for the development. Use the following command to install all python dependencies.
```
pip install -r requirements.txt
```


## Usage
The entire process is splitted in 5 steps.
 - Prepare minizinc problems
 - Compile minizinc problems into flatzinc
 - Solve flatzinc problems with different configurations
 - Collect the statistics
 - Plot the results

### Minizinc
First, you have to prepare your problem sources in [minizinc](/minizinc) directory. You have to create one subdirectory per problem. Within each directory, place the minizinc model and all datazinc files. If you want to try the system you can use the minizinc examples.
```
cp -r examples minizinc
```

Remark: for now the system only supports one mzn file with at least at least one dzn file per problem.

### Compilation
Use the following command to compile all problem instances into flatzinc.
```
just compile
```
You should now have all flatzinc files under [flatzinc](/flatzinc) directory.

### Resolution
You have can solve the problems either locally or using slurm. In both cases, you should obtain the solutions and CSV statistics in [results](/results) directory.

Remark: since the results are always saved in [results/tmp](/results/tmp) you should never try to solve the problems twice at the same time.

#### Local resolution
To solve the problems locally use the following command. You can specify the timeout for each instance using the justfile variable `TIMEOUT`. The arguments after `solve` are given to the solver binary.
```
just TIMEOUT=1s solve --var-order lexical --value-order max --restart never
```

#### Slurm resolution
Use the following command to prepare the resolution using slurm. You can specify the timeout for each instance using the justfile variable `TIMEOUT` and the job timeout using `JOB_TIMEOUT`. The arguments after `slurm` are given to the solver binary.
```
just TIMEOUT=1s dry-slurm --var-order lexical --value-order max --restart never
```
Once you are ready for the execution you can remove `dry` prefix. You can control the job progression using the following command.
```
just watch
```
In case of problem, you can check the slurm outputs which are saved in `slurm` directory.

#### Rename
Once the resolution is done, the results are saved in [results/tmp](/results/tmp). You should now rename this directory with a name indicating the configuration parameters. It should be of the form `varorder_valueorder_restart`. Use the following command to do this.
```
just rename lexical_min_never
```

### Collection
Now you one CSV file per problem instance, it is time to collect all the results for each configuration. For this, enter the following command.
```
just collect
```
You should now have one file `results.csv` within each subdirectory of [results](/results).

### Plot
Once you have collected all the results you need, it is time for the most funny part... plotting! All supported plots and their options are documented via the CLI. Use the following command to show it.
```
just plot --help
```

Remark: most of the plots have CLI options to customize axes, colors... feel free to use.


## Reference

### Bash scripts
To keep the justfile as minimal as possible, most of the work is done in bash scripts. All of them are stored in [scripts](/scripts) directory.

To ensure all the variables are consistent across all the files, they are stored in the justfile. Their values are transfered to the script using the command line arguments.

### Python plot script
The python script [plot.py](/scripts/plot.py) uses three libraries. The CLI is written with argparse. The dataframe are created using polars. Finally the plots are generated with plotly. All the source code is commented so it should not be too difficult to understand how it works.


## Documentation
You can find the documentation in [doc](/doc) directory.

### Database schema
The database schema ie the dataframes and their columns are described in [database.puml](doc/database.puml). The plantuml file format is eaily readable in text format but you can also generate the diagram using a vscode extension or the [online editor](https://editor.plantuml.com/). If you modify the database structure, do not forget to update the documentation.

### Score metrics
You can find all details about the score metrics used in [scores](/doc/scores) directory. Everything is explained in [SCORES.md](/doc/scores/SCORES.md).


## Perspectives
Here are possible ways to improve the system, in no particular order.
- Improve robustness for run with no solution.
- Relax the configuration pattern `varorder_valueorder_restart` constraint.
- Modify [collect.sh](/scripts/collect.sh) to gather all the results in one file.
- Add support for satisfaction problems.
- Add support for OPTIMAL and UNSAT statuses.
- Generalize the system to any kind of problem, not necesarily minizinc.


## Useful links
- [Aries](https://github.com/plaans/aries)
- [MiniZinc documentation](https://docs.minizinc.dev/en/stable/index.html)
- [MiniZinc playground](https://play.minizinc.dev/)
- [minizinc-benchmark](https://github.com/MiniZinc/minizinc-benchmarks)
- [Just](https://github.com/casey/just)
- [Polars](https://docs.pola.rs/py-polars/html/reference/)
- [Plotly API](https://plotly.com/python-api-reference/index.html)
- [Plotly gallery](https://plotly.com/python/)
- [PlantUML](https://plantuml.com/)
- [PlantUML editor](https://editor.plantuml.com/)
- [Argparse documentation](https://docs.python.org/3/library/argparse.html)
