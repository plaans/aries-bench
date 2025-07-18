# Score metrics
This document describe the metrics used to compare two or more solver configurations.

## Notations
- $ \cal{C} $ - set of solver configurations
- $ n_c $ - number of solutions for configuration $c$
- $ s_{i,c} $ - objective value of the $i^{th}$ solution of configuration $c$
- $ t_{i,c} $ - time of the $i^{th}$ solution of configuration $c$
- $ u_c = \max_i s_{i,c} $ - objective upper bound for configuration $c$
- $ l_c = \min_i s_{i,c} $ - objective lower bound for configuration $c$
- $ b_c = s_{n_c,c} $ - best objective value for configuration $c$
- $ w_c = s_{1,c} $ - worst objective value for configuration $c$
- $ u = \max_c u_c $ - objective upper bound for all configurations
- $ l = \min_c l_c $ - objective upper bound for all configurations
- $ b = \min_c u_c \text{ or } \max_c u_c $ - best objective value for any configuration
- $ w = \max_c l_c \text{ or } \min_c l_c $ - worst objective value for any configuration


## Objective
The objective score is defined as a length ratio.

![Objective score figure](/doc/scores/objective/objective.png)

The objective score of a configuration $c$ is defined as follows.
$$ \text{o}_c = \frac{|b_c - b|}{u - l} $$


## Area under the curve
The area under the curve score is defined as an area ratio. We first define the area under the curve for minimization problems. It will easily generalize at the end.

![Area under curve score figure](/doc/scores/auc/auc.png)


First we need to compute the bounding box area.
$$ \cal{A} = (u - l) (\max_{i,c} t_{i,c} - \max_{i,c} t_{i,c}) $$

Then we compute the area under the curve of configuration $c$. To simplify the formula, we add a virtual solution not improving the objective. Let $ s_{n_c+1,c} = s_{n_c,c} $ and $ t_{n_c+1,c} = \max_{i,c} t_{i,c} $.
$$ \cal{A}_c = \sum_{i=1}^{n} s_{i,c} (t_{i+1,c} - t_{i,c})$$

The area under the curve score is the area ratio.
$$ \text{auc}_c = \frac{\cal{A}_c}{\cal{A}} $$

For maximization problems, we compute the area above the curve.
$$ \text{auc}_c' = \frac{\cal{A} - \cal{A}_c}{\cal{A}} = 1 - \text{auc}_c $$

Remark: we can replace the time by any strictly increasing sequence such as the number of decisions.
