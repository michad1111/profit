"""proFit main script.

This script is called when running the `profit` command.
"""

from os import getcwd, path
import sys
from argparse import ArgumentParser, RawTextHelpFormatter

try:
    from tqdm import tqdm
except ModuleNotFoundError:
    def tqdm(x): return x

from profit.config import Config
from profit.util import safe_path_to_file
from profit.util.io import read_input, collect_output

yes = False  # always answer 'y'


def fit(x, y):
    from profit.sur.gp import GPySurrogate
    fresp = GPySurrogate()
    fresp.train(x, y)
    return fresp


def fill_uq(self, krun, content):
    params_fill = SafeDict()
    kp = 0
    for item in self.params:
        params_fill[item] = self.eval_points[kp, krun]
        kp = kp+1
    return content.format_map(params_fill)


def main():
    """
    Main command line interface
    sys.argv is an array whose values are the entered series of command
    (e.g.: sys.argv=['profit','run', '--active-learning', '/home/user/example'])
    """

    """ Get parameters from argv """
    parser = ArgumentParser(usage='profit <mode> (base-dir)',
                            description="Probabilistic Response Model Fitting with Interactive Tools",
                            formatter_class=RawTextHelpFormatter)
    parser.add_argument('mode',
                        metavar='mode',
                        choices=['pre', 'run', 'collect', 'fit', 'ui'],
                        help='pre ... prepare simulation runs based on templates \n'
                             'run ... start simulation runs \n'
                             'collect ... collect simulation output \n'
                             'fit ... fit data with Gaussian Process \n'
                             'ui ... visualise results')
    parser.add_argument('base_dir',
                        metavar='base-dir',
                        help='path to config file (default: current working directory)',
                        default=getcwd(), nargs='?')
    args = parser.parse_args()

    print(args)

    """ Instantiate Config class from the given file """
    config_file = safe_path_to_file(args.base_dir, default='profit.yaml')
    config = Config.from_file(config_file)

    sys.path.append(config['base_dir'])

    if args.mode == 'pre':
        from profit.pre import fill_run_dir, get_eval_points

        """ Get input points ready to fill run directory """
        eval_points = get_eval_points(config)

        try:
            fill_run_dir(eval_points, template_dir=config['template_dir'],
                         run_dir=config['run_dir'], overwrite=False)
        except RuntimeError:
            question = "Warning: Run directories in {} already exist " \
                       "and will be overwritten. Continue? (y/N) ".format(config['run_dir'])
            if yes:
                print(question+'y')
            else:
                answer = input(question)
                if not answer.lower().startswith('y'):
                    print('exit...')
                    sys.exit()

            fill_run_dir(eval_points, template_dir=config['template_dir'],
                         run_dir=config['run_dir'], overwrite=True)

    elif args.mode == 'run':
        from profit.run import LocalCommand

        # TODO: Include options (in call or in config file) which run backend should be used.
        print(read_input(config['run_dir']))
        try:
            run = LocalCommand(config['run']['cmd'], config['run']['ntask'],
                               run_dir=config['run_dir'], base_dir=config['base_dir'])
            run.start()
        except KeyError:
            raise RuntimeError("No 'run' entry in profit.yaml")
        except FileNotFoundError:
            # TODO: Error occurs in single threads and is written to stderr.
            #       Make it easier for the user to recognise this error
            pass

    elif args.mode == 'collect':

        try:
            collect_output(config)
        except ImportError:
            question = "Interface could not be imported. Try with default interface? (y/N)"
            if yes:
                print(question+'y')
            else:
                answer = input(question)
                if not answer.lower().startswith('y'):
                    print('exit...')
                    sys.exit()

            collect_output(config, default_interface=True)

    elif args.mode == 'fit':
        from numpy import loadtxt
        from profit.fit import get_surrogate

        x = loadtxt(config['files']['input'])
        y = loadtxt(config['files']['output'])
        sur = get_surrogate(config['fit']['surrogate'])

        if config['fit'].get('load'):
            sur = sur.load_model(path.join(config['base_dir'], config['fit']['load']))
        else:
            sur.train(x, y)
            # TODO: plot_searching_phase

        if config['fit'].get('save'):
            sur.save_model(path.join(config['base_dir'], config['fit']['save']))
        if config['fit'].get('plot'):
            sur.plot()

    elif args.mode == 'ui':
        from profit.ui import app
        app.app.run_server(debug=True)


if __name__ == '__main__':
    main()
