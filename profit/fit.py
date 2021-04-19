from profit.sur.sur import Surrogate
import numpy as np
from tqdm import tqdm


class ActiveLearning:
    """Class for active learning of hyperparameters. Needs references to runner and surrogate."""
    _defaults = {'nrand': 3, 'optimize_every': 1, 'plot_every': False, 'al_range': (0, 1), 'save': False}

    def __init__(self, runner, surrogate, inputs):
        """Initialize class with interface to runner and surrogate and create variables for AL parameters."""
        self.runner = runner  # Runner object
        self.sur = surrogate  # Surrogate object
        self.inputs = inputs  # input dict from config
        self.al_keys = [key for key in self.inputs if self.inputs[key]['kind'] == 'ActiveLearning']  # variable names for AL
        self.al_ranges = [self.inputs[key]['al_range'] for key in self.al_keys]  # Range of these variables
        self.X = self.runner.flat_input_data  # Input training data
        self.y = None  # Observed output data
        self.Xpred = None  # Prediction points
        self.nrand = None  # Nr. of runs with random points before active learning starts
        self.ntrain = None  # total number of training runs  # TODO: leave this open and specify a convergence criterion instead
        self.optimize_every = None  # nr of AL iterations between hyperparameter optimizations
        self.plot_every = False  # nr of AL iterations between plotting the progress

    def run_first(self, nrand=3):
        """Run first simulations with random points."""
        from profit.util.variable_kinds import uniform, halton
        self.nrand = self.nrand or nrand
        params_array = [{} for _ in range(self.nrand)]
        halton_seq = halton(size=(self.nrand, len(self.al_keys)))
        for idx, (key, rng) in enumerate(zip(self.al_keys, self.al_ranges)):
            for n in range(self.nrand):
                params_array[n][key] = (rng[1]-rng[0]) * halton_seq[n, idx] + rng[0]  #uniform(start=rng[0], end=rng[1], size=1)
        self.runner.spawn_array(params_array, blocking=True)
        self.X = self.runner.flat_input_data
        self.y = self.runner.flat_output_data
        self.sur.train(self.X[:self.nrand], self.y[:self.nrand], return_hess_inv=True)

    def update_run(self, krun, al_value):
        """Update input and execute a single run."""
        params = {}
        for pos, key in enumerate(self.inputs):
            if key in self.al_keys:
                params[key] = al_value[pos]
                self.X[krun, pos] = al_value[pos]
        # Start single run
        self.runner.spawn_run(params, wait=True)
        # Read output (all available data)
        self.y = self.runner.flat_output_data

    @classmethod
    def from_config(cls, runner, config, base_config):
        """Instantiate an ActiveLearning class from the configuration parameters."""
        sur = Surrogate.from_config(base_config['fit'], base_config)
        self = cls(runner, sur, base_config['input'])
        self.nrand = config['nrand']
        self.ntrain = base_config['ntrain']
        self.optimize_every = config['optimize_every']
        self.plot_every = config['plot_every']
        self.Xpred = config.get('Xpred')
        return self

    @classmethod
    def handle_config(cls, config, base_config):
        """Set default values in configuration, if not existent."""
        if config is None:
            config = {'ActiveLearning': {}}

        for key, default in cls._defaults.items():
            if key not in config:
                config[key] = default

        for key, value in base_config['input'].items():
            if value['kind'] == 'ActiveLearning':
                if not value.get('al_range'):
                    value['al_range'] = cls._defaults['al_range']
        if config.get('save'):
            from os import path
            config['save'] = path.join(base_config['base_dir'], config['save'])

    @staticmethod
    def f(u):
        """ Example for debugging. """
        return np.cos(10 * u) + u

    def learn(self, ntrain=None, Xpred=None, optimize_every=1, plot_every=False):
        """Main loop for active learning."""
        self.ntrain = self.ntrain or ntrain  # Set variable either from config or from given parameter
        self.optimize_every = self.optimize_every or optimize_every
        self.plot_every = self.plot_every or plot_every
        if self.plot_every:
            from matplotlib.pyplot import figure, show

        self.Xpred = self.Xpred or Xpred or self.sur.default_Xpred()
        if isinstance(self.Xpred, list):  # Create a dense predictive array for each dimension
            xp = [np.arange(minv, maxv, step) for minv, maxv, step in self.Xpred]
            self.Xpred = np.hstack([xi.flatten().reshape(-1, 1) for xi in np.meshgrid(*xp)])

        # Main loop
        for krun in tqdm(range(self.nrand, self.ntrain)):
            try:
                marginal_variance = self.sur.get_marginal_variance(self.Xpred)
            except AttributeError:
                # Surrogate must have marginal variance calculation
                raise RuntimeError("Surrogate {} is not suited for Active Learning!".format(self.sur.__class__.__name__))

            # Find next candidate
            if np.max(marginal_variance.max(axis=0) - marginal_variance.min(axis=0)) >= 1e-5:
                loss = marginal_variance / marginal_variance.max() + self.additional_loss(self.X[krun - 1].reshape(1, -1))
                loss /= loss.max()
                if self.plot_every and not (krun+1) % self.plot_every and self.plot_marginal_variance:
                    if self.Xpred.shape[-1] > 1:
                        ax[1].plot_trisurf(self.Xpred[:, 0], self.Xpred[:, 1], loss.flatten())
                    else:
                        ax[1].plot(self.Xpred, loss)
                al_value = self.Xpred[np.argmax(loss)]
            else:
                al_value = self.Xpred[np.random.randint(self.Xpred.shape[0])]
            self.update_run(krun, al_value)
            self.sur.add_training_data(self.X[krun].reshape(1, -1), self.y[krun].reshape(1, -1))
            if not (krun+1) % self.optimize_every:
                self.sur.optimize(return_hess_inv=True)  # Optimize hyperparameters
            if self.plot_every and not (krun+1) % self.plot_every:
                figure()  # Plot progress in new figure
                self.sur.plot(self.Xpred, ref=self.f)

        if self.plot_every:
            show()

    def additional_loss(self, last_point):
        """Penalize candidates which are near to the previous point."""
        return 1.0 - np.exp(-0.5 * np.linalg.norm(self.Xpred - last_point, axis=1).reshape(-1, 1))

    def save(self, path):
        self.sur.save_model(path)
