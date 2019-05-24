# %%
import datetime
import numpy as np
from scipy.sparse import diags
from scipy import integrate


@np.vectorize
def int_rate(x):
    return 0.05


class Underlying(object):
    """
    We currently use prescribed drift and volatility for simplicity of the
    project. Implied volatility tools amongst others will be built at a
    later phase.

    We expect all time entries to be datetime form.
    """

    def __init__(self, spot_time, spot_price, dividend=0.0):
        self.time = spot_time
        self.price = spot_price
        self.drift = None  # get these later
        self.vol = 0.2  # TODO: this part need to be changed
        self.div = dividend


class Option(object):

    def __init__(self, otype, expiry_date):
        self.otype = otype
        self.expiry = expiry_date

    def _attach_asset(self, strike_price, *underlyings):
        self.strike = strike_price
        self.int_rate = int_rate
        self.spot_price = []
        self.currency = []
        self._time = []
        self._vol = []  # TODO: This need to be modified when get data
        self._drift = []
        for underlying in underlyings:
            self.spot_price.append(underlying.price)
            self._time.append(underlying.time)
            self._vol.append(underlying.vol)
            self._drift.append(underlying.drift)
            self.div = underlying.div
        if len(self._time) == 1:
            self.time_to_maturity = self.expiry - self._time[0]
        else:
            raise ValueError('Undelyings have different spot times')

    def payoff(self, price):
        if self.otype == 'call':
            return np.clip(price - self.strike, 0, None).astype(float)
        elif self.otype == 'put':
            return np.clip(self.strike - price, 0, None).astype(float)
        else:
            raise ValueError('Incorrect option type')


class EurOption(Option):
    """
    we write this subclass just to make the structure clearer.
    AmeOption can be seen as EurOptio when dealing with pricing.
    """

    def __init__(self, otype, expiry):
        super().__init__(otype, expiry)

    def gen_pde_coeff(self):
        try:
            end_time = self.time_to_maturity.days / 365  # use start = 0
        except ValueError:
            raise ("Underlying not attached")

        @np.vectorize
        def coef2(asset, t):
            return (sum(self._vol) * asset) ** 2 / 2

        @np.vectorize
        def coef1(asset, t):
            return (int_rate(t) - self.div) * asset

        @np.vectorize
        def coef0(asset, t):
            return -int_rate(t)
        return end_time, [coef2, coef1, coef0]


class AmeOption(Option):

    def __init__(self, otype, expiry):
        super().__init__(otype, expiry)


class BarOption(EurOption):  # Barrier options
    """
    Currently this class only consider call/put options with knock-out barriers.
    Further knock-in features will be built up in a later phase.
    """

    def __init__(self, otype, expiry, rebate=0):
        super().__init__(otype, expiry)
        self.rebate = rebate

    def _attach_asset(self, barrier, strike_price, *underlyings):
        """
        barrier expect a list := [lower_bar, higher_bar]. If one of barrier does
        not exist, write None e.g., an down option has barrier = [lower_bar, None]
        """
        try:
            super()._attach_asset(strike_price, *underlyings)
            self.barrier = barrier
        except TypeError as e:
            # TODO: How to overwrite parent exceptions?
            print(f"{e} or Forget to write barrier?")

    # def payoff(self, price):
    #     lower_bar, higher_bar = self.barrier
    #     if self.otype == 'call':
    #         price = np.clip(price - self.strike, 0, higher_bar).astype(float)
    #     elif self.otype == 'put':
    #         price = np.clip(self.strike - price, lower_bar, higher_bar).astype(float)
    #     else:
    #         raise Exception('Unknown option type')
    #     price[price == lower_bar], price[price == higher_bar] = self.rebate, self.rebate
    #     return price
        # This is forced as x >= None is deprecated in python3.


a = EurOption('call', datetime.datetime(2011, 1, 1))
b = Underlying(datetime.datetime(2010, 1, 1), 100)
a._attach_asset(100, b)

# %%


def gen_grid(low_val, high_val, start_time, end_time, asset_no = 10, time_no = 100):
    time_samples = np.linspace(start_time, end_time, time_no)
    asset_samples = np.linspace(low_val, high_val, asset_no)
    X, Y = np.meshgrid(asset_samples, time_samples)
    return X, Y

#%%


def load_sim(model):
    end_time, [coef2, coef1, coef0] = model.gen_pde_coeff()
    spot_price = sum(model.spot_price)  # TODO: Change this part when vectorize
    X, Y = gen_grid(0, 5 * spot_price, 0, end_time)
    # TODO: This price range can later be scaled up to paramters.
    time_no = X.shape[0]
    step_no = X.shape[1]
    dS, dt = X[0, 1] - X[0, 0], Y[1, 0] - Y[0, 0]
    v1, v2 = dt / (dS ** 2), dt / dS
    A = (v1 * coef2(X, Y) / 2 - v2 * coef1(X, Y) / 4).T
    B = (-v1 * coef2(X, Y) + dt * coef0(X, Y) / 2).T
    C = (v1 * coef2(X, Y) / 2 + v2 * coef1(X, Y) / 4).T
    return A, B, C, X, Y, time_no, step_no, spot_price

# %%

def boundary_condition(model):
    """
    This part accounts for boundary condition. By default we use Dirichlet
    boundary condition for barrier option. If it's not barrier option, then for
    vanilla option we switch to Neumann boundary condition.

    WARNING: To make sure this boundary_condition function properly, we need to
    make the simulation range large enough.
    """
    A, B, C, X, Y, time_no, step_no, spot_price = load_sim(model)
    try:  # use Dirchlet boundary condition
        lower_lvl, upper_lvl = model.barrier
        lower = np.full(time_no, float(lower_lvl or 0))  # change None to 0
        upper = np.full(time_no, float(upper_lvl or 0))
        if model.otype == 'call':
            lower = np.maximum(np.zeros(time_no), lower)
            upper = np.minimum(upper,
                               X[-1, -1] * np.exp(-model.div * (Y[-1, -1] - Y[:, 0])) -
                               model.strike * np.exp(-model.int_rate(Y[:, 0]) * (Y[-1, -1] - Y[:, 0])))
        # TODO: hard-coded. need to changed
        elif model.otype == 'put':
            upper = np.maximum(np.zeros(time_no), upper)
            lower = np.minimum(lower,
                               -X[0, 0] * np.exp(-model.int_rate(Y[:, 0]) * (Y[-1, -1] - Y[:, 0])) +
                               model.strike * np.exp(-model.div * (Y[-1, -1] - Y[:, 0])))
        else:  # use Neumann Boundary condition
            raise ValueError('Unknown option type')
    except AttributeError:  # use von Neumann boundary condition
        if model.otype == "call":
            lower = 0
            upper = X[0, 1] - X[0, 0]
        if model.otype == "put":
            lower = X[0, 0] - X[0, 1]  # only a concise notation of previous
            upper = 0
    except:
        raise Exception('Invalid model type')
    finally:
        return lower, upper


def option_price_all(model):
    """
    Prepare coefficient now. For convience we follow convention of Wilmott.
    """
    A, B, C, X, Y, time_no, step_no, spot_price = load_sim(model)
    lower, upper = boundary_condition(model)
    """
    Prepare 3D tensor (time-list of sparse diagonal matrix) for simulation.
    Later only expand one slice to full matrix so as to save storage.
    """
    matrix_left = [diags((-A[:, i], 1-B[:, i], -C[:, i]), offsets=[0, 1, 2],
                         shape=(step_no, step_no + 2)) for i in range(time_no)]
    matrix_right = [diags((A[:, i], 1+B[:, i], C[:, i]), offsets=[0, 1, 2],
                          shape=(step_no, step_no + 2)) for i in range(time_no)]

    """the following is not fully optimised.
    But as that is not related to linear system, we can ignore it (partially)"""
    try:  # for barrier option case, use Dirchlet.
        lower_bar, higher_bar = model.barrier
        lower_bar, higher_bar = float(
            lower_bar or 0), float(higher_bar or np.inf)
        out = model.payoff(X[0][1:-1])
        damp_layer = np.where((X[0][1:-1] <= lower_bar)
                              | (X[0][1:-1] >= higher_bar))
        out[damp_layer] = model.rebate
        total_output = [out]
        lower_bdd = lower * A[1]
        upper_bdd = upper * C[-2]
        for time_pt in range(1, time_no):
            mat_left, mat_right = matrix_left[-time_pt -
                                              1].A, matrix_right[-time_pt].A
            mat_left, mat_right = mat_left[1:-1, 2:-2], mat_right[1:-1, 2:-2]
            extra_vec = np.zeros(step_no-2)
            extra_vec[[0, -1]] = lower_bdd[-time_pt] + lower_bdd[-time_pt - 1], \
                upper_bdd[-time_pt] + upper_bdd[-time_pt - 1]
            out = np.linalg.solve(mat_left, mat_right @ out + extra_vec)
            out[damp_layer] = model.rebate
            total_output.append(out)
        # TODO: Note the shape of dirichlet output is diff from von Neumann
        # total_output = np.vstack(np.full((1, time_no), time_no),
        #                 total_output, np.full(1, time_no, np.inf))
    except AttributeError:  # For vanilla option case, use von Neumann
        out = model.payoff(X[0])
        total_output = [out]
        lower_bdd = lower * A[0]
        upper_bdd = upper * C[-2]
        for time_pt in range(1, time_no):
            mat_left, mat_right = matrix_left[-time_pt -
                                              1].A, matrix_right[-time_pt].A
            mat_left[:, [2, -3]] += mat_left[:, [0, -1]]
            mat_right[:, [2, -3]] += mat_right[:, [0, -1]]
            mat_left, mat_right = mat_left[:, 1:-1], mat_right[:, 1:-1]
            extra_vec = np.zeros(step_no)
            extra_vec[[0, -1]] = lower_bdd[-time_pt] + lower_bdd[-time_pt - 1],
            upper_bdd[-time_pt] + upper_bdd[-time_pt - 1]
            out = np.linalg.solve(mat_left, mat_right @ out + extra_vec)
            total_output.append(out)
    return total_output


def option_price_begin(model):
    return option_price_all(model)[-1]

# In[ ]:


'''all the boundary_condition will be initiated after testing'''


def boundary(option='call', barrier=False):
    if barrier and option == 'call':
        lower_bdd = np.zeros(time_no)
        upper_bdd = -strike_price * \
            np.exp(-back_quad(int_rate, time_samples)) + high_val * \
            np.exp(-back_quad(div_rate, time_samples))
    if barrier and option == 'put':
        lower_bdd = -low_val * np.exp(-back_quad(div_rate, time_samples)) + \
            strike_price * np.exp(-back_quad(int_rate, time_samples))
        upper_bdd = np.zeros(time_no)
    else:
        raise Exception('Unknown option type')
