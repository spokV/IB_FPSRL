from keras import backend as K, optimizers
from keras.models import Sequential, load_model
from keras.layers import RNN, Layer
import numpy as np
from argparse import ArgumentParser
from misc.dicts import load_cfg
from misc.files import ensure_can_write
import os


class S_RNNCell(Layer):
    def __init__(self, units, state_size, self_input, z_dim, a_dim, **kwargs):
        self.units = units
        self.state_size = (units, state_size)
        self.self_input = self_input
        self.output_size = units
        self.z_dim = z_dim
        self.a_dim = a_dim
        super().__init__(**kwargs)

    def get_config(self):
        base_config = super().get_config()
        base_config.update({
            'units': self.units,
            'state_size': self.state_size[1],
            'self_input': self.self_input,
            'z_dim': self.z_dim,
            'a_dim': self.a_dim
        })
        return base_config

    def build(self, input_shape):
        assert len(input_shape) == 2  # Only batch size and a vector dimension
        assert input_shape[1] == (self.z_dim + self.a_dim)
        self.A_weights = self.add_weight(name='A', shape=(self.state_size[1], self.state_size[1]), initializer='uniform')
        self.B_weights = self.add_weight(name='B', shape=(self.state_size[1], self.state_size[1]), initializer='uniform')
        self.C_weights = self.add_weight(name='C', shape=(self.z_dim + (1 if self.self_input else 0), self.state_size[1]), initializer='uniform')
        self.D_weights = self.add_weight(name='D', shape=(self.a_dim, self.state_size[1]), initializer='uniform')
        self.E_weights = self.add_weight(name='E', shape=(self.state_size[1], self.units), initializer='uniform')
        self.bias = self.add_weight(name='bias', shape=(self.state_size[1],), initializer='uniform')
        super().build(input_shape)

    def call(self, inputs, states):
        y_prev = states[0]
        si_prev = states[1]
        z = inputs[:,:self.z_dim]
        if self.self_input:
            z = K.concatenate((z, y_prev), axis=1)
        a = inputs[:,self.z_dim:]
        s = K.tanh(K.dot(si_prev, self.A_weights) + K.dot(z, self.C_weights))
        si = K.tanh(K.dot(s, self.B_weights) + K.dot(a, self.D_weights) + self.bias)
        y = K.dot(si, self.E_weights)
        return y, [y, si]


def generate_world_model(cfg, clean = False):
    write_to = cfg['model_output_file']
    gen_cfg = cfg['generation']
    learning_cfg = cfg['learning']
    if os.path.isfile(write_to) and not clean:
        return load_model(write_to, custom_objects={ 'S_RNNCell': S_RNNCell })

    training_data = np.load(cfg['data_output_file'])
    training_input = np.concatenate((training_data['z'], training_data['a']), axis=2)
    training_output = training_data['y']

    # Shuffle training data
    shuffled_indices = np.arange(len(training_data))
    np.random.shuffle(shuffled_indices)
    training_input = training_input[shuffled_indices]
    training_output = training_output[shuffled_indices]

    STATE_DIM = learning_cfg['state_dim']
    SELF_INPUT = learning_cfg['self_input']

    Z_DIM = np.shape(training_data.dtype[0])[1]  # includes self-input
    assert 0 < Z_DIM
    A_DIM = np.shape(training_data.dtype[1])[1]
    assert 0 < A_DIM
    Y_DIM = np.shape(training_data.dtype[2])[1]
    assert 0 < Y_DIM

    UNROLL_PAST = gen_cfg['past_window']
    assert 0 < UNROLL_PAST
    UNROLL_FUTURE = gen_cfg['future_window']
    assert 0 <= UNROLL_FUTURE
    for i in range(len(training_data.dtype)):
        assert np.shape(training_data.dtype[i])[0] == UNROLL_PAST + UNROLL_FUTURE

    cell = S_RNNCell(Y_DIM, STATE_DIM, SELF_INPUT, Z_DIM, A_DIM)
    model = Sequential()
    model.add(RNN(cell, return_sequences=True))

    print('Starting training')
    base_lr = learning_cfg['learning_rate']
    steps = learning_cfg['learning_rate_steps']
    for lr in map(lambda exp: base_lr * (0.5 ** exp), range(steps)):
        opt = optimizers.RMSprop(lr=lr)
        model.compile(optimizer=opt, loss='mean_squared_error', metrics=['mean_absolute_percentage_error'])
        model.fit(training_input, training_output,
            validation_split=learning_cfg['validation_split'],
            verbose=1,
            batch_size=learning_cfg['batch_size'],
            epochs=learning_cfg['epochs']
        )

    print('Serializing trained model')
    ensure_can_write(write_to)
    model.save(write_to)

    return model


if __name__ == '__main__':
    parser = ArgumentParser(description='Create and train a neural net for a world model')
    parser.add_argument('cfg_file')
    parser.add_argument('-c', '--clean', action='store_true')
    args = parser.parse_args()
    cfg = load_cfg(args.cfg_file)
    generate_world_model(cfg, args.clean)
