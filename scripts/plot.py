from __future__ import annotations
import argparse
import dataclasses
from pathlib import Path
import sys
from types import ModuleType
import plotly.express as px
import plotly.subplots
import plotly.graph_objects as go
import polars as pl
import polars.selectors as cs

def add_prefix(df: pl.DataFrame, prefix: str, dot: str = ".") -> pl.DataFrame:
    """Add the given prefix on all columns without a dot of the dataframe.
    
    Example:
    id, name, age, friend.id -> p.id, p.name, p.age, friend.id
    """
    return df.rename({
        column: prefix + dot + column 
        for column in df.columns 
        if dot not in column
    })


def cast_duration(df: pl.DataFrame) -> pl.DataFrame:
    """Cast duration to i64 number of microseconds.

    This is a fix for `timedelta is not JSON serializable`."""
    return df.with_columns(
        pl.col(pl.Duration).dt.total_microseconds(),
    )




@dataclasses.dataclass
class Database:
    """Collection of dataframes."""
    raw_df: pl.DataFrame
    problem_df: pl.DataFrame
    flatzinc_df: pl.DataFrame
    run_df: pl.DataFrame
    configuration_df: pl.DataFrame
    event_df: pl.DataFrame

    # Mapping from problem type to arrow
    PROBLEM_TYPE_ARROW = {
        "maximize": "↑",
        "minimize": "↓",
    }

    @staticmethod
    def read(results_dir: Path, improve: bool = True) -> Database:
        """Read all CSV files within results directory and return a new Database object."""
        raw_df = Database.read_raw_df(results_dir)
        problem_df = Database.make_problem_df(raw_df)
        flatzinc_df = Database.make_flatzinc_df(raw_df, problem_df)
        configuration_df = Database.make_configuration_df(raw_df)
        run_df = Database.make_run_df(raw_df, problem_df, flatzinc_df, configuration_df)
        event_df = Database.make_event_df(raw_df, problem_df, flatzinc_df, configuration_df, run_df)
        db = Database(
            raw_df=raw_df,
            problem_df=problem_df,
            flatzinc_df=flatzinc_df,
            configuration_df=configuration_df,
            run_df=run_df,
            event_df=event_df,
        )
        if improve:
            db.improve()
        return db


    @staticmethod
    def read_raw_df(results_dir: Path) -> pl.DataFrame:
        """Read all CSV files within results directory and return a raw dataframe."""
        sub_dfs = []

        # Read
        for configuration in results_dir.iterdir():
            if not configuration.is_dir():
                continue
            csv_file = configuration / "results.csv"
            sub_df = pl.read_csv(csv_file)

            sub_df.insert_column(
                index = 0,
                column = pl.lit(configuration.name).alias("configuration"),
            )

            sub_dfs.append(sub_df)

        # Gather all dataframes in one
        df: pl.DataFrame = pl.concat(sub_dfs, rechunk=True)

        # Convert time to duration
        df = df.with_columns(
            pl.duration(microseconds=pl.col("time")).alias("time"),
        )

        schema = {
            "configuration": pl.Categorical(ordering="lexical"),
            "problem": pl.Categorical(ordering="lexical"),
            "flatzinc": pl.Categorical(ordering="lexical"),
            "type": pl.Enum(categories=["start", "new_solution"]),
            "num_solutions": pl.UInt64,
            "objective": pl.Int64,
            "time": pl.Duration(time_unit="us"),
            "num_decisions": pl.UInt64,
            "num_conflicts": pl.UInt64,
            "num_dom_updates": pl.UInt64,
            "num_restarts": pl.UInt64,
        }

        # Verify the columns fit the schema
        expected_columns = list(schema.keys())
        if df.columns != expected_columns:
            print(f"expected columns for raw dataframe: {expected_columns}", file=sys.stderr)
            print(f"  actual columns for raw dataframe: {df.columns}", file=sys.stderr)

        assert df.columns == expected_columns

        # Cast columns
        df = df.cast(schema)

        return df


    @staticmethod
    def make_problem_df(raw_df: pl.DataFrame) -> pl.DataFrame:
        """Make problem dataframe from raw dataframe."""
        df = raw_df.select("problem").unique()

        df = df.rename({"problem": "name"})

        df = df.sort("name")
        df = df.with_row_index("id")

        # Problem name must be unique
        assert df.get_column("name").is_unique().all()

        return df


    @staticmethod
    def make_flatzinc_df(raw_df: pl.DataFrame, problem_df: pl.DataFrame) -> pl.DataFrame:
        """Make flatzinc dataframe from raw and problem dataframes."""
        df = raw_df.select("problem", "flatzinc").unique()

        # Join on problem names
        df = df.join(
            problem_df.select("name", "id"),
            left_on="problem",
            right_on="name",
            how="left"
        )

        # Drop problem name
        df = df.drop("problem")

        # Rename columns
        df = df.rename({
            "flatzinc": "name",
            "id": "problem.id",
        })

        # Sort on problem then name
        df = df.sort("problem.id", "name")

        # The pair (name, problem.id) must be unique
        assert df.select("name", "problem.id").is_unique().all()

        df = df.with_row_index("id")

        return df


    @staticmethod
    def make_configuration_df(raw_df: pl.DataFrame) -> pl.DataFrame:
        """Make configuration dataframe from raw dataframe."""
        df = raw_df.select("configuration").unique()

        # Extract variable order, value order and restart policy from the name
        df = df.with_columns(
            pl.col("configuration").cast(pl.String)
            .str.split_exact("_", 2)
            .struct.rename_fields(["var_order", "value_order", "restart"])
            .alias("fields"),
        ).unnest("fields")

        # Cast heuristic columns to categorical
        df = df.cast({
            "var_order": pl.Categorical(ordering="lexical"),
            "value_order": pl.Categorical(ordering="lexical"),
            "restart": pl.Categorical(ordering="lexical"),
        })

        df_nulls = df.filter(pl.col("restart").is_null())

        # Print error messages for wrong configuration name
        for configuration in df_nulls.get_column("configuration"):
            print(f"configuration '{configuration}' is not of the form varorder_valueorder_restart", file=sys.stderr)
        
        assert df_nulls.is_empty(), "a configuration is not of the form varorder_valueorder_restart"

        df = df.rename({
            "configuration": "name",
        })

        # Sort on name
        df = df.sort("name")
        df = df.with_row_index("id")

        return df


    @staticmethod
    def make_run_df(
            raw_df: pl.DataFrame,
            problem_df: pl.DataFrame,
            flatzinc_df: pl.DataFrame,
            configuration_df: pl.DataFrame
        ) -> pl.DataFrame:
        """Make configuration dataframe from raw, problem, flatzinc and configuration dataframes."""

        fzn_df = flatzinc_df.join(
            problem_df.select("id", "name"),
            left_on="problem.id",
            right_on="id"
        ).rename({
            "name_right": "problem.name",
            "name": "flatzinc.name",
            "id": "flatzinc.id",
        })

        df = raw_df.select("configuration", "problem", "flatzinc").unique()
        
        # Join for flatzinc id
        df = df.join(
            fzn_df,
            left_on=("problem", "flatzinc"),
            right_on=("problem.name", "flatzinc.name"),
        )

        # Join for configuration id
        df = df.join(
            configuration_df.select("name", "id"),
            left_on="configuration",
            right_on="name",
        )

        df = df.rename({
            "id": "configuration.id",
        })

        df = df.select("flatzinc.id", "configuration.id")

        # Pair (flatzinc.id, configuration.id) should be unique
        assert df.is_unique().all()

        # Sort on flatzinc then configuration
        df = df.sort("flatzinc.id", "configuration.id")
        df = df.with_row_index("id")

        return df


    @staticmethod
    def make_event_df(
            raw_df: pl.DataFrame,
            problem_df: pl.DataFrame,
            flatzinc_df: pl.DataFrame,
            configuration_df: pl.DataFrame,
            run_df: pl.DataFrame,
        ) -> pl.DataFrame:
        """Make configuration dataframe from raw, problem, flatzinc and configuration dataframes."""

        fzn_df = flatzinc_df.join(
            problem_df.select("id", "name"),
            left_on="problem.id",
            right_on="id"
        ).rename({
            "name_right": "problem.name",
            "name": "flatzinc.name",
            "id": "flatzinc.id",
        })

        id_df = run_df.join(
            fzn_df,
            on="flatzinc.id",
            how="left",
        ).join(
            configuration_df.select("id", "name"),
            left_on="configuration.id",
            right_on="id",
            how="left",
        ).rename({
            "id": "run.id",
            "name": "configuration.name",
        })

        df = raw_df.join(
            id_df,
            left_on=("configuration", "problem", "flatzinc"),
            right_on=("configuration.name", "problem.name", "flatzinc.name"),
            how="left"
        )

        # Keep all columns but configuration, problem, flatzinc
        columns = raw_df.columns[3:]
        columns.insert(0, "run.id")

        df = df.select(columns)

        # Sort by run then time
        df = df.sort("run.id", "time")
        df = df.with_row_index("id")

        return df


    def add_problem_type(self) -> None:
        """Add problem type depending on objective variations."""

        # Check if a run is increasing and/or decreasing
        df = self.event_df.group_by("run.id").agg(
            (pl.col("objective") - pl.col("objective").shift() > 0).any().alias("increase"),
            (pl.col("objective") - pl.col("objective").shift() < 0).any().alias("decrease"),
        )

        # A run is monotonic iff objective is not decreasing and increasing
        df = df.with_columns(
            (pl.col("increase").not_() | pl.col("decrease").not_()).alias("monotonic"),
        )

        # Collect configuration, flatzinc and problem names for debug output
        df_not_monotonic = df.filter(pl.col("monotonic").not_()).join(
            add_prefix(self.run_df, "run"),
            on="run.id",
        ).join(
            add_prefix(self.configuration_df, "configuration"),
            on="configuration.id",
        ).join(
            add_prefix(self.flatzinc_df, "flatzinc"),
            on="flatzinc.id",
        ).join(
            add_prefix(self.problem_df, "problem"),
            on="problem.id",
        ).select("problem.name", "flatzinc.name", "configuration.name")

        # Print error messages for non-monotonic runs
        for row in df_not_monotonic.iter_rows():
            problem, flatzinc, configuration = row
            print(
                f"objective value of '{flatzinc}' from '{problem}' runned with '{configuration}' is not monotonic",
                file=sys.stderr
            )
        
        assert df_not_monotonic.is_empty(), "there is a run with non-monotonic objective"

        df = df.join(
            add_prefix(self.run_df, "run"),
            on="run.id",
        ).join(
            add_prefix(self.flatzinc_df, "flatzinc"),
            on="flatzinc.id",
        ).join(
            add_prefix(self.problem_df, "problem"),
            on="problem.id",
        )

        # Check monotonicity for a problem
        df = df.group_by("problem.id", "problem.name").agg(
            pl.col("increase").any(),
            pl.col("increase").sum().alias("num_increase"),
            pl.col("decrease").sum().alias("num_decrease"),
        )

        # Get problems with both increasing and decreasing runs
        df_both = df.filter(
            (pl.col("num_decrease") != 0) & (pl.col("num_increase") != 0)
        ).select("problem.id", "num_decrease", "num_increase")
        
        # Print error messages for each non monotonic problem
        for row in df_both.iter_rows():
            problem, num_decrease, num_increase = row
            print(f"problem '{problem}' has {num_decrease} decreasing runs and {num_increase} increasing", file=sys.stderr)

        assert df_both.is_empty(), "there is a problem with both increasing and decreasing flatzinc"

        # Problem is maximise iff increase
        df = df.with_columns(
            pl.when("increase").then(pl.lit("maximize")).otherwise(pl.lit("minimize")).alias("type"),
        )

        # Make enum for problem type
        df = df.cast({
            "type": pl.Enum(categories=["minimize", "maximize"]),
        })

        df = df.rename({
            "problem.id": "id",
            "problem.name": "name",
        })

        df = df.select("id", "name", "type")
        df = df.sort("id")

        assert df.get_column("name").is_sorted()

        # Overwrite problem dataframe
        self.problem_df = df
    

    def propagate_type_to_flatzinc(self) -> None:
        """Propagate the problem type to flatzinc dataframe."""

        df = self.flatzinc_df.join(
            self.problem_df.select("id", "type"),
            left_on="problem.id",
            right_on="id",
            how="left",
        )

        df = df.rename({
            "type": "problem.type",
        })

        self.flatzinc_df = df
    

    def add_objective_bounds(self) -> None:
        """Add objective bounds to run and flatzinc dataframes."""

        # Compute objective lower and upper bounds
        df = self.event_df.group_by("run.id").agg(
            pl.min("objective").alias("objective_lb"),
            pl.max("objective").alias("objective_ub"),
        )

        # Join run, event, flatzinc and problem dataframes
        df = self.run_df.join(
            df,
            left_on="id",
            right_on="run.id",
            how="left",
        ).join(
            self.flatzinc_df.select("id", "problem.type"),
            left_on="flatzinc.id",
            right_on="id",
        )

        # Compute objective best and worst bounds
        df = df.with_columns(
            pl.when(pl.col("problem.type") == "minimize")
                .then("objective_lb")
                .otherwise("objective_ub")
                .alias("objective_bb"),
            pl.when(pl.col("problem.type") == "minimize")
                .then("objective_ub")
                .otherwise("objective_lb")
                .alias("objective_wb"),
        )

        self.run_df = df.select(*self.run_df.columns, cs.starts_with("objective"))

        assert self.run_df.get_column("id").is_sorted()

        df = df.group_by("flatzinc.id", "problem.type").agg(
            pl.min("objective_lb"),
            pl.max("objective_ub"),
        )

        # Compute objective best and worst bounds
        df = df.with_columns(
            pl.when(pl.col("problem.type") == "minimize")
                .then("objective_lb")
                .otherwise("objective_ub")
                .alias("objective_bb"),
            pl.when(pl.col("problem.type") == "minimize")
                .then("objective_ub")
                .otherwise("objective_lb")
                .alias("objective_wb"),
        )

        df = df.drop("problem.type")

        df = self.flatzinc_df.join(
            df,
            left_on="id",
            right_on="flatzinc.id",
            how="left",
        )

        self.flatzinc_df = df
    

    def add_num_solutions(self) -> None:
        """Add number of solutions to run dataframe."""

        df = self.event_df.group_by("run.id").agg(
            pl.max("num_solutions"),
        )

        df = self.run_df.join(
            df,
            left_on="id",
            right_on="run.id",
            how="left",
        )

        self.run_df = df
    

    def add_objective_score(self) -> None:
        """Add objective score to run dataframe."""

        df = self.run_df.join(
            add_prefix(self.flatzinc_df.select("id", cs.starts_with("objective")), "flatzinc"),
            on="flatzinc.id",
        )

        # Compute the objective score
        df = df.with_columns(
            (
                (pl.col("objective_bb") - pl.col("flatzinc.objective_bb")).abs() / 
                (pl.col("flatzinc.objective_ub") - pl.col("flatzinc.objective_lb"))
            ).alias("objective_score"),
        )

        # Drop flatzinc objective values
        df = df.drop(cs.starts_with("flatzinc.objective"))

        self.run_df = df


    def add_bounds(self, col: str) -> None:
        """Add bounds to run and flatzinc dataframes for a given column e.g. time.
        It adds fsol and lsol in column name for first solution and last solution."""

        # Only keep new solution events
        event_df = self.event_df.filter(
            pl.col("type") == "new_solution",
        )

        # Compute value of the first and last solution of a run
        df = event_df.group_by("run.id").agg(
            pl.min(col).alias(f"{col}_fsol"),
            pl.max(col).alias(f"{col}_lsol"),
        )

        df = self.run_df.join(
            df,
            left_on="id",
            right_on="run.id",
            how="left",
        )

        self.run_df = df

        # Compute value of the first and last solution of a flatzinc
        df = self.run_df.group_by("flatzinc.id").agg(
            pl.min(f"{col}_fsol").alias(f"{col}_fsol"),
            pl.max(f"{col}_lsol").alias(f"{col}_lsol"),
        )

        df = self.flatzinc_df.join(
            df,
            left_on="id",
            right_on="flatzinc.id",
            how="left",
        )

        self.flatzinc_df = df
    

    def add_auc_score(self, col: str, name: str = "auc_score") -> None:
        """Add area under the curve score to run dataframe.

        The score represents the ratio between area under objective-time curve
        and the area of the bounding box of all solution points in the same plot."""

        # Extract column value, objective and run id for new solutions
        df = self.event_df.filter(
            pl.col("type") == "new_solution",
        ).select("run.id", col, "objective")

        # Compute area under the curve
        df = df.group_by("run.id").agg(
            (pl.col("objective") * (pl.col(col) - pl.col(col).shift()))
            .sum()
            .alias("area_under_curve"),
        )

        # Extract interesting columns from run dataframe
        run_df = self.run_df.select(
            "id",
            "flatzinc.id",
            "objective_bb",
            "objective_wb",
            f"{col}_fsol",
            f"{col}_lsol",
        )

        # Join on run dataframe
        df = run_df.join(
            df,
            left_on="id",
            right_on="run.id",
            how="left",
        )

        # Compute rectangle area for flatzinc
        flatzinc_df = self.flatzinc_df.select(
            "id",
            "problem.type",
            "objective_ub",
            "objective_lb",
            f"{col}_fsol",
            f"{col}_lsol",
        ).with_columns(
            (
                (pl.col("objective_ub") - pl.col("objective_lb"))
                * (pl.col(f"{col}_lsol") - pl.col(f"{col}_fsol"))
            ).alias("rectangle_area")
        )
        
        # Join on flatzinc dataframe
        df = df.join(
            add_prefix(flatzinc_df, "flatzinc"),
            on="flatzinc.id",
            how="left",
        )

        # Check the run bounds are correct compared to flatzinc bounds
        assert df.get_column(f"{col}_fsol").ge(df.get_column(f"flatzinc.{col}_fsol")).all()
        assert df.get_column(f"{col}_lsol").le(df.get_column(f"flatzinc.{col}_lsol")).all()
        assert df.get_column("objective_wb").ge(df.get_column("flatzinc.objective_lb")).all()
        assert df.get_column("objective_bb").ge(df.get_column("flatzinc.objective_lb")).all()
        assert df.get_column("objective_wb").le(df.get_column("flatzinc.objective_ub")).all()
        assert df.get_column("objective_bb").le(df.get_column("flatzinc.objective_ub")).all()

        # Compute area inside flatzinc rectangle
        df = df.with_columns(
            (
                + pl.col("area_under_curve") 
                + (pl.col(f"{col}_fsol") - pl.col(f"flatzinc.{col}_fsol")) * pl.col("objective_wb")
                + (pl.col(f"flatzinc.{col}_lsol") - pl.col(f"{col}_lsol")) * pl.col("objective_bb") 
                - (pl.col(f"flatzinc.{col}_lsol") - pl.col(f"flatzinc.{col}_fsol")) * pl.col("flatzinc.objective_lb")
            ).alias("area"),
        )

        # Compute area ratio with the rectangle
        df = df.with_columns(
            (pl.col("area") / pl.col("flatzinc.rectangle_area")).alias("area_ratio"),
        )

        # Compute auc score using problem type
        df = df.with_columns(
            pl.when(pl.col("problem.type") == "minimize")
            .then("area_ratio")
            .otherwise(1.0 - pl.col("area_ratio"))
            .alias(name),
        )

        df = df.select("id", name)

        self.run_df = self.run_df.join(
            df,
            on="id",
            how="left"
        )


    def improve(self) -> None:
        """Improve the dataframes by adding columns. This should only be called once."""
        self.add_problem_type()
        self.propagate_type_to_flatzinc()
        self.add_objective_bounds()
        self.add_num_solutions()
        self.add_objective_score()
        self.add_bounds("time")
        self.add_bounds("num_decisions")
        self.add_auc_score("time", "autc_score")
        self.add_auc_score("num_decisions", "audc_score")


def make_subplots(
        db: Database,
        x_col: str,
        y_col: str,
        palette: list[str] = plotly.colors.qualitative.Plotly,
        line_shape: str = "linear",
        row_height: int = 200,
    ) -> go.Figure:
    """Return a figure containing one plot per flatzinc, one color per configuration."""

    # Cast duration to avoid issue with duration
    db_event_df = cast_duration(db.event_df)

    # Prepare the colors for configurations
    configurations = db.configuration_df.get_column("id")
    num_configurations = configurations.count()
    colors = [palette[i % len(palette)] for i in range(num_configurations)]
    configuration_color = dict(zip(configurations, colors))

    num_rows = len(db.problem_df)
    num_cols = db.flatzinc_df.group_by("problem.id").agg(
        pl.col("id").count().alias("count"),
    ).get_column("count").max()

    figure = plotly.subplots.make_subplots(
        rows=num_rows,
        cols=num_cols,
        subplot_titles=tuple(" " for _ in range(num_rows*num_cols)),
        row_titles=list(db.problem_df.get_column("name")),
    )

    for i, problem_row in enumerate(db.problem_df.iter_rows()):
        (problem_id, problem_name, problem_type, *_) = problem_row

        print(f"Problem {problem_name}:")
        flatzinc_df = db.flatzinc_df.filter(pl.col("problem.id") == problem_id)

        for j, flatzinc_row in enumerate(flatzinc_df.iter_rows()):
            flatzinc_id, flatzinc_name, *_ = flatzinc_row
            print(f" - {flatzinc_name}")

            for configuration_row in db.configuration_df.iter_rows():
                configuration_id, configuration_name, *_ = configuration_row

                run_df = db.run_df.filter(
                    pl.col("configuration.id") == configuration_id,
                    pl.col("flatzinc.id") == flatzinc_id,
                )

                # If no run available: skip
                if len(run_df) == 0:
                    continue

                # The run should be unique
                assert len(run_df) == 1, f"several runs with configuration.id={configuration_id} and flatzinc.id={flatzinc_id}"

                run_id = run_df.item(0,0)

                event_df = db_event_df.filter(pl.col("run.id") == run_id)

                color = configuration_color[configuration_id]

                trace = go.Scatter(
                    x=event_df.get_column(x_col),
                    y=event_df.get_column(y_col),
                    showlegend=False,
                    line={"color": color, "shape": line_shape},
                    name=configuration_name,
                    mode="lines+markers",
                )
                figure.add_trace(trace, row=i+1, col=j+1)

                # Add vertical line for end 
                # TODO use event type == end
                max_x = event_df.get_column(x_col).max()
                figure.add_vline(
                    x=max_x,
                    row=i+1,
                    col=j+1,
                    line={"color": color, "width": 1},
                )

            # Add vertical line for start
            figure.add_vline(x=0, row=i+1, col=j+1)

            # Add title to subplot
            arrow = db.PROBLEM_TYPE_ARROW[problem_type]
            subplot_title = f"{flatzinc_name} - {flatzinc_id}{arrow}"
            k = i*num_cols + j
            figure.layout.annotations[k].update(text=subplot_title)
        
        print("")

    figure.update_layout(
        height=row_height*num_rows,
        title=f"Subplots   -   x={x_col}   y={y_col}",
    )

    return figure


def make_flatzinc_plot(
        db: Database,
        x_col: str,
        y_col: str,
        flatzinc_id: int,
        palette: list[str] = plotly.colors.qualitative.Plotly,
        line_shape: str = "linear",
    ) -> go.Figure:
    """Create a line plot for the given flatzinc."""

    # Get flatzinc name and objective bound
    flatzinc_df = db.flatzinc_df.filter(
        pl.col("id") == flatzinc_id,
    ).select("name", "problem.id", "problem.type")

    assert len(flatzinc_df) == 1
    
    flatzinc_name, problem_id, problem_type = flatzinc_df.row(0)

    # Get problem name
    problem_name = db.problem_df.filter(
        pl.col("id") == problem_id,
    ).select("name").item()

    # Keep run on the given flatzinc
    run_df = db.run_df.filter(
        pl.col("flatzinc.id") == flatzinc_id,
    )

    # Only keep new solution points
    df = db.event_df.filter(
        pl.col("type") == "new_solution",
    )

    # Cast duration to avoid issue with serialization
    df = cast_duration(df)

    df = df.join(
        run_df,
        left_on="run.id",
        right_on="id",
    ).join(
        db.configuration_df.select("id", "name"),
        left_on="configuration.id",
        right_on="id",
    ).rename({
        "name": "configuration.name",
    })

    figure = px.line(
        data_frame=df,
        x=x_col,
        y=y_col,
        color="configuration.name",
        color_discrete_sequence=palette,
        hover_name="configuration.name",
        line_shape=line_shape,
        markers=True,
        title=f"{problem_name} - {flatzinc_name}",
        subtitle=f"{flatzinc_id} - {problem_type}",
    )

    max_df = df.group_by("configuration.id", maintain_order=True).agg(
        pl.max(x_col),
    )

    # Add vertical lines 
    # TODO use event type == end
    for i, max_x in enumerate(max_df.get_column(x_col)):
        color=palette[i % len(palette)]
        figure.add_vline(
            x=max_x,
            line={"color": color, "width": 1},
        )

    # Global min and max on x and y axes
    min_x = df.get_column(x_col).min()
    max_x = df.get_column(x_col).max()
    min_y = df.get_column(y_col).min()
    max_y = df.get_column(y_col).max()

    figure.add_shape(
        type="rect",
        x0=min_x,
        y0=min_y,
        x1=max_x,
        y1=max_y,
        layer="between",
        line={"width": 1},
    )

    return figure


def make_heatmap_plot(
        db: Database,
        z_col: str,
        palette: list[str] = plotly.colors.sequential.Plasma,
        q0: float = 0.1,
        q1: float = 0.9,
    ) -> go.Figure:
    """Create a heatmap configuration-flatzinc. The color is given by z_col from run dataframe ."""

    # Control quantiles validity
    assert 0.0 <= q0 and q0 <= 1.0
    assert 0.0 <= q1 and q1 <= 1.0
    assert q0 < q1

    df = db.run_df.join(
        add_prefix(db.configuration_df.select("id", "name"), "configuration"),
        on="configuration.id",
    ).join(
        add_prefix(db.flatzinc_df.select("id", "name", "problem.id"), "flatzinc"),
        on="flatzinc.id",
    ).join(
        add_prefix(db.problem_df.select("id", "name"), "problem"),
        on="problem.id",
    )

    # Add info in flatzinc name: problem first letters and id
    df = df.with_columns(
        pl.format(
            "{}. - {} - {}",
            pl.col("problem.name").cast(pl.String).str.slice(0, 3),
            "flatzinc.name",
            "flatzinc.id"
        ).alias("flatzinc.name"),
    )

    # Cast duration to avoid issue with serialization
    df = cast_duration(df)

    num_flatzincs = len(db.flatzinc_df)

    # Remove outliers via q0 and q1 for color bar
    min_color = df.get_column(z_col).quantile(q0)
    max_color = df.get_column(z_col).quantile(q1)

    figure = px.density_heatmap(
        df,
        y="flatzinc.name",
        x="configuration.name",
        color_continuous_scale=palette,
        z=z_col,
        text_auto=True,
        height=25*num_flatzincs,
        range_color=(min_color,max_color),
    )

    # Set color bar title and change orientation
    figure.update_coloraxes(colorbar={"title": z_col, "orientation":"h"})

    # Disable hover
    figure.update_traces(hoverinfo="skip", hovertemplate=None)

    # Remove axis titles
    figure.update_layout(xaxis_title=None, yaxis_title=None)

    return figure


def make_box_plot(
        db: Database,
        y_col: str,
        palette: list[str] = plotly.colors.qualitative.Plotly,
        log: bool = False,
        notched: bool = False,
    ) -> go.Figure:
    """Create a line plot for the given flatzinc."""

    # Get configuration, flatzinc and problem name
    df = db.run_df.join(
        add_prefix(db.configuration_df.select("id", "name"), "configuration"),
        on="configuration.id",
        how="left",
    ).join(
        add_prefix(db.flatzinc_df.select("id", "name", "problem.id"), "flatzinc"),
        on="flatzinc.id",
        how="left",
    ).join(
        add_prefix(db.problem_df.select("id", "name"), "problem"),
        on="problem.id",
        how="left",
    )
    
    figure = px.box(
        df,
        x="configuration.name",
        y=y_col,
        color="configuration.name",
        color_discrete_sequence=palette,
        hover_data=["problem.name", "flatzinc.name", "flatzinc.id"],
        points="all",
        log_y=log,
        notched=notched,
        title="Box plot",
    )

    # Remove x-axis title
    figure.update_layout(xaxis_title=None)

    return figure



def check_column(column: str, df: pl.DataFrame, df_name: str) -> str:
    """Return an error message if column is not in the dataframe. 
    Otherwise it returns an empty string."""
    message = ""
    if column not in df.columns:
        valid_values = ", ".join(df.columns)
        message += f"'{column}' is not a valid column for {df_name} dataframe.\n"
        message += f"valid values are: {valid_values}"
    return message


def get_palette(name: str, name_palette: dict[str, list[str]]) -> list[str]:
    """Get the palette of the given name.
    Raise KeyError with CLI error message if not found."""
    palette = name_palette.get(name)
    if palette is None:
        valid_values = ", ".join(filter(lambda n: not n.endswith("_r"), name_palette.keys()))
        message = f"'{name}' is not a color palette.\n"
        message += f"valid values are: {valid_values}\n"
        message += "add '_r' to reverse the color scale"
        raise KeyError(message)
    return palette


def describe(name: str, df: pl.DataFrame) -> str:
    """Create a string description of the dataframe."""
    description = f"{name} {df.shape}:"
    for column, dtype in df.schema.items():
        description += f"\n - {column} {dtype}"
    return description


def get_dataframes(db: Database, name: str) -> list[tuple[str,pl.DataFrame]]:
    """Return the dataframe(s) of the given name."""
    db_dict = dataclasses.asdict(db)
    df_suffix = "_df"
    all_df_names = [
        name
        for name in db_dict.keys()
        if name.endswith(df_suffix)
    ]

    dfs: list[tuple[str,pl.DataFrame]]

    if args.dataframe is None:
        dfs = [(name, db_dict[name]) for name in all_df_names]
    else:
        name: str = args.dataframe.removesuffix(df_suffix) + df_suffix
        if name not in all_df_names:
            valid_values = ", ".join(
                name.removesuffix(df_suffix) 
                for name in all_df_names
            )
            print(f"'{args.dataframe}' is not a valid dataframe name", file=sys.stderr)
            print(f"valid values are: {valid_values}", file=sys.stderr)
            raise ValueError()
        else:
            dfs = [(name, db_dict[name])]
    
    return dfs


def get_named_palettes(module: ModuleType) -> dict[str, list[str]]:
    """Return mapping lower name - palette."""
    name_palette = dict()
    for name in dir(module):
        if name.startswith("_"):
            continue
        palette = getattr(module, name)
        # A palette is a list of at least one string
        if isinstance(palette, list) and len(palette) != 0 and isinstance(palette[0], str):
            name_palette[name.lower()] = palette
    return name_palette


def dev_cmd(args: argparse.Namespace) -> int:
    """Command to develop things."""
    # This command should never do something
    # It is just an easy entry point to test things
    return 0


def print_cmd(args: argparse.Namespace) -> int:
    """Command to print dataframe."""
    db: Database = args.db
    basic: bool = args.basic

    if not basic:
        db.improve()

    try:
        dfs = get_dataframes(db, args.dataframe)
    except ValueError:
        return 1
    
    for name, df in dfs:
        columns = ", ".join(df.columns)
        print(name, df)
        print(columns, "\n")
    
    return 0


def describe_cmd(args: argparse.Namespace) -> int:
    """Command to describe dataframe."""
    db: Database = args.db
    basic: bool = args.basic

    if not basic:
        db.improve()

    try:
        dfs = get_dataframes(db, args.dataframe)
    except ValueError:
        return 1
    
    for name, df in dfs:
        print(describe(name, df), "\n")
    
    return 0


def heatmap_cmd(args: argparse.Namespace) -> int:
    """Command to create a heatmap plot."""
    db: Database = args.db
    z_col: str = args.z
    palette_name: str = args.color
    q0: float = args.q0
    q1: float = args.q1
    reverse_color: bool = args.reverse_color

    if error_message := check_column(z_col, db.run_df, "run"):
        print(error_message, file=sys.stderr)
        return 1

    reverse_suffix = "_r"
    if reverse_color:
        if palette_name.endswith(reverse_suffix):
            palette_name = palette_name.removesuffix(reverse_suffix)
        else:
            palette_name = palette_name + reverse_suffix

    name_palette = get_named_palettes(plotly.colors.sequential)
    try:
        palette = get_palette(palette_name.lower(), name_palette)
    except KeyError as e:
        print(e.args[0], file=sys.stderr)
        return 1

    if q0 >= q1:
        print("q0 must be strictly less than q1", file=sys.stderr)
        return 1

    figure = make_heatmap_plot(
        db,
        z_col=z_col,
        palette=palette,
        q0=q0,
        q1=q1,
    )
    figure.show()
    return 0


def flatzinc_cmd(args: argparse.Namespace) -> int:
    """Command to create a flatzinc plot."""
    db: Database = args.db
    x_col: str = args.x
    y_col: str = args.y
    flatzinc_ids: list[int] = args.id
    palette_name: str = args.color
    line_shape: str = args.line

    # Check column names
    for col in (x_col, y_col):
        if error_message := check_column(col, db.event_df, "event"):
            print(error_message, file=sys.stderr)
            return 1
    
    # Get color palette
    name_palette = get_named_palettes(plotly.colors.qualitative)
    try:
        palette = get_palette(palette_name.lower(), name_palette)
    except KeyError as e:
        print(e.args[0], file=sys.stderr)
        return 1

    for flatzinc_id in flatzinc_ids:
        if flatzinc_id not in db.flatzinc_df.get_column("id"):
            print(f"warning: '{flatzinc_id}' is not a valid flatzinc id", file=sys.stderr)
            print(f"eg use 'subplots' command to see all flatzinc ids", file=sys.stderr)
            continue
        figure = make_flatzinc_plot(
            db,
            x_col=x_col,
            y_col=y_col,
            flatzinc_id=flatzinc_id,
            palette=palette,
            line_shape=line_shape,
        )
        figure.show()
    return 0


def subplots_cmd(args: argparse.Namespace) -> int:
    """Command to create a subplots figure."""
    db: Database = args.db
    x_col: str = args.x
    y_col: str = args.y
    palette_name: str = args.color
    line_shape: str = args.line
    row_height: int = args.row_height

    # Check column names
    for col in (x_col, y_col):
        if error_message := check_column(col, db.event_df, "event"):
            print(error_message, file=sys.stderr)
            return 1
    
    # Get color palette
    name_palette = get_named_palettes(plotly.colors.qualitative)
    try:
        palette = get_palette(palette_name.lower(), name_palette)
    except KeyError as e:
        print(e.args[0], file=sys.stderr)
        return 1
    
    figure = make_subplots(
        db,
        x_col=x_col,
        y_col=y_col,
        palette=palette,
        line_shape=line_shape,
        row_height=row_height,
    )
    figure.show()
    return 0


def box_cmd(args: argparse.Namespace) -> int:
    """Command to create a box plot."""
    db: Database = args.db
    y_col: str = args.y
    palette_name: str = args.color
    log: bool = args.log
    notched: bool = args.notched

    # Check y column name
    if error_message := check_column(y_col, db.run_df, "run"):
        print(error_message, file=sys.stderr)
        return 1
    
    # Get color palette
    name_palette = get_named_palettes(plotly.colors.qualitative)
    try:
        palette = get_palette(palette_name.lower(), name_palette)
    except KeyError as e:
        print(e.args[0], file=sys.stderr)
        return 1

    figure = make_box_plot(
        db,
        y_col=y_col,
        palette=palette,
        log=log,
        notched=notched,
    )
    figure.show()
    return 0


def main(args: argparse.Namespace) -> int:
    """Execute the actions specified in the arguments."""

    # Set plotly renderer to browser
    plotly.io.renderers.default = "browser"

    # Read the results to make the database
    args.db = Database.read(args.results_dir, args.improve_db)
    
    exit_code = args.cmd_callback(args)
    return exit_code


def float_01(arg: str) -> float:
    """Argparse function for float in [0,1]."""
    try:
        x = float(arg)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{arg}' is not a float literal")

    if x < 0.0 or x > 1.0:
        raise argparse.ArgumentTypeError(f"{x} is not in range [0,1]")
    return x



def make_cli() -> argparse.ArgumentParser:
    """Create the CLI using argparse."""

    parser = argparse.ArgumentParser(
        prog=Path(__file__).name,
        description="Tool to plot aries resolution statistics."
    )
    parser.set_defaults(improve_db=True)

    parser.add_argument(
        "results_dir",
        help="directory containing all the results",
        type=Path,
    )

    subparsers = parser.add_subparsers(
        title="commands",
        metavar="CMD",
        required=True,
    )

    # ----------

    dev_parser = subparsers.add_parser(
        "dev",
        description="Entry point to test things.",
    )
    dev_parser.set_defaults(cmd_callback=dev_cmd)

    # ----------

    describe_parser = subparsers.add_parser(
        "describe",
        description="Print the schema of the given dataframe. "
            "If no dataframe is given, all schemas are printed.",
        help="describe dataframes",
    )
    describe_parser.set_defaults(cmd_callback=describe_cmd)
    describe_parser.set_defaults(improve_db=False)

    describe_parser.add_argument(
        "dataframe",
        help="name of the dataframe to describe",
        nargs="?",
    )

    describe_parser.add_argument(
        "--basic",
        help="do not improve database",
        action="store_true",
    )

    # ----------

    print_parser = subparsers.add_parser(
        "print",
        description="Print the given dataframe. "
            "If no dataframe is given, all dataframes are printed.",
        help="print dataframes",
    )
    print_parser.set_defaults(cmd_callback=print_cmd)
    print_parser.set_defaults(improve_db=False)

    print_parser.add_argument(
        "dataframe",
        help="name of the dataframe to print",
        nargs="?",
    )

    print_parser.add_argument(
        "--basic",
        help="do not improve database",
        action="store_true",
    )

    # ----------

    heatmap_parser = subparsers.add_parser(
        "heatmap",
        description="Create a heatmap plot with one cell per run. "
            "You can change the color axis using z option.",
        help="create heatmap plot",
    )
    heatmap_parser.set_defaults(cmd_callback=heatmap_cmd)

    heatmap_parser.add_argument(
        "-z",
        help="z axis column from run dataframe",
        default="objective_score",
        metavar="COL",
    )

    heatmap_parser.add_argument(
        "-c", "--color",
        help="sequential color palette",
        default="plasma",
        metavar="P",
    )

    heatmap_parser.add_argument(
        "-r", "--reverse-color",
        help="reverse color palette",
        action="store_true",
    )

    heatmap_parser.add_argument(
        "-q0",
        help="quantum for minimal color value (%(default)s)",
        default=0.1,
        metavar="Q",
        type=float_01,
    )

    heatmap_parser.add_argument(
        "-q1",
        help="quantum for maximal color value (%(default)s)",
        default=0.9,
        metavar="Q",
        type=float_01,
    )

    # ----------

    flatzinc_parser = subparsers.add_parser(
        "flatzinc",
        description="Create a flatzinc plot showing evolution objective value. "
            "You can can change the axes using x and y options.",
        help="create flatzinc plot",
    )
    flatzinc_parser.set_defaults(cmd_callback=flatzinc_cmd)

    flatzinc_parser.add_argument(
        "-x",
        help="x axis column from event dataframe",
        default="num_decisions",
        metavar="COL",
    )

    flatzinc_parser.add_argument(
        "-y",
        help="y axis column from event dataframe",
        default="objective",
        metavar="COL",
    )

    flatzinc_parser.add_argument(
        "-c", "--color",
        help="qualitative color palette",
        default="plotly",
        metavar="P",
    )

    flatzinc_parser.add_argument(
        "-l", "--line",
        help="line shape (%(default)s)",
        choices=["linear", "spline", "hv", "vh", "hvh", "vhv"],
        default="hv",
        metavar="S",
    )

    flatzinc_parser.add_argument(
        "id",
        help="flatzinc id",
        type=int,
        nargs="+",
    )

    # ----------

    subplots_parser = subparsers.add_parser(
        "subplots",
        description="Create a big figure with one subplot per flatzinc. "
            "Each subplot shows the evolution of the objective. "
            "You can can change the axes using x and y options.",
        help="create one subplot per flatzinc",
    )
    subplots_parser.set_defaults(cmd_callback=subplots_cmd)

    subplots_parser.add_argument(
        "-x",
        help="x axis column from event dataframe",
        default="num_decisions",
        metavar="COL",
    )

    subplots_parser.add_argument(
        "-y",
        help="y axis column from event dataframe",
        default="objective",
        metavar="COL",
    )

    subplots_parser.add_argument(
        "-l", "--line",
        help="line shape (%(default)s)",
        choices=["linear", "spline", "hv", "vh", "hvh", "vhv"],
        default="hv",
        metavar="S",
    )

    subplots_parser.add_argument(
        "-c", "--color",
        help="qualitative color palette",
        default="plotly",
        metavar="P",
    )

    subplots_parser.add_argument(
        "-rh", "--row-height",
        help="row height in pixel",
        default=200,
        type=int,
    )

    # ----------

    box_parser = subparsers.add_parser(
        "box",
        description="Create a box plot showing objective score for each configuration. "
            "You can can change the y axis using y option.",
        help="create box plot",
    )
    box_parser.set_defaults(cmd_callback=box_cmd)

    box_parser.add_argument(
        "-y",
        help="y axis column from run dataframe",
        default="objective_score",
        metavar="COL",
    )

    box_parser.add_argument(
        "-c", "--color",
        help="qualitative color palette",
        default="plotly",
        metavar="P",
    )

    box_parser.add_argument(
        "--log",
        help="use logarithmic scale",
        action="store_true",
    )

    box_parser.add_argument(
        "--notched",
        help="show box notches",
        action="store_true",
    )

    return parser


if __name__ == "__main__":
    parser = make_cli()
    args = parser.parse_args()
    exit_code = main(args)
    sys.exit(exit_code)
