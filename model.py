import numpy as np
import tensorflow as tf
import transformer
from midi_to_encoding import *
from midi_to_fig import *
import sys
import random
import os
from utils import encoding_to_midi



class Transformer(tf.keras.Model):
    def __init__(self):

        super(Transformer, self).__init__()


        # Hyperparameters
        self.batch_size = tf.Variable(40, trainable=False)
        self.embedding_size = tf.Variable(50, trainable=False)
        self.hidden_layer_size = tf.Variable(50, trainable=False)
        # 0.01 performs better than 0.001, try 0.005
        self.learning_rate = tf.Variable(0.01, trainable=False)
        self.num_epochs = tf.Variable(1, trainable=False)
        # max window size for full data set
        
        # temp window size for subset of data
        self.window_size = tf.Variable(6000, trainable=False)
        self.space_index = tf.Variable(412, trainable=False)
        self.padding_index = tf.Variable(413, trainable=False)
        self.num_heads = tf.Variable(1, trainable=False)
        self.vocab_size = tf.Variable(414, trainable=False)

        # generation hyper params
        self.max_phrase_length = tf.Variable(7, trainable=False)
        self.phrase_rand_amount = tf.Variable(3, trainable=False)

        self.train = tf.Variable(False, trainable=False)



        # Optimizer
        self.optimizer = tf.keras.optimizers.Adam(learning_rate=self.learning_rate)

        # Define english and french embedding layers:
        self.encoder_emb = tf.keras.layers.Embedding(self.vocab_size.numpy(), self.embedding_size.numpy())
        self.decoder_emb = tf.keras.layers.Embedding(self.vocab_size.numpy(), self.embedding_size.numpy())

        # Positional embedding not necessary in this implementation (apparently)

        # Define encoder and decoder layers:
        self.encoder = transformer.Transformer_Block(self.embedding_size.numpy(), False, self.window_size.numpy(), num_heads=self.num_heads.numpy())
        self.decoder = transformer.Transformer_Block(self.embedding_size.numpy(), True, self.window_size.numpy(), num_heads=self.num_heads.numpy())

        # Define dense layer(s)
        self.dense_1 = tf.keras.layers.Dense(self.hidden_layer_size.numpy(), activation="relu")
        self.dense_2 = tf.keras.layers.Dense(self.vocab_size.numpy(), activation="softmax")

    @tf.function
    def call(self, encoder_input):
        """
        :param encoder_input:
        :param decoder_input:
        :return prbs: Probabilities as a tensor, [batch_size x window_size x input_size]
        """

        #1) Embed the encoder_input

        encoder_embedded = self.encoder_emb(encoder_input)

        #2) Pass the encoder_input embeddings to the encoder
        context = self.encoder(encoder_embedded)

        #3) Embed the decoder_input
        decoder_embedded = self.decoder_emb(encoder_input)

        #4) Pass the decoder_input embeddings and result of the encoder to the decoder
        decoded = self.decoder(decoder_embedded, context)

        #5) Apply dense layers to the decoder out to generate probabilities
        result = self.dense_1(decoded)
        result = self.dense_2(result)

        return result

    def accuracy_function(self, prbs, labels, mask):
        """
        Computes the batch accuracy

        :param prbs:  float tensor, prediction probabilities [batch_size x window_size x input_size]
        :param labels:  integer tensor, prediction labels [batch_size x window_size]
        :param mask:  tensor that acts as a padding mask [batch_size x window_size]
        :return: scalar tensor of accuracy of the batch between 0 and 1
        """

                # Masking may not be necessary
                
        decoded_symbols = tf.argmax(input=prbs, axis=2)
        accuracy = tf.reduce_mean(tf.boolean_mask(tf.cast(tf.equal(decoded_symbols, labels), dtype=tf.float32),mask))
        return accuracy


    def loss_function(self, prbs, labels, mask):
        """
        Calculates the model cross-entropy loss after one forward pass
        Please use reduce sum here instead of reduce mean to make things easier in calculating per symbol accuracy.

        :param prbs:  float tensor, word prediction probabilities [batch_size x window_size x input_size]
        :param labels:  integer tensor, word prediction labels [batch_size x window_size]
        :param mask:  tensor that acts as a padding mask [batch_size x window_size]
        :return: the loss of the model as a tensor
        """

        # Implement negative log likelyhood
        # Masking may not be necessary

        return tf.reduce_sum(tf.boolean_mask(tf.keras.losses.sparse_categorical_crossentropy(labels, prbs, False), mask))

    # @av.call_func
    # def __call__(self, *args, **kwargs):
    # 	return super(Transformer_Seq2Seq, self).__call__(*args, **kwargs)


def train(model):
    """
    Runs through one epoch - all training examples.

    :param model: the initialized model to use for forward and backward pass
    :param train_data: (num_midis, window_size)
    :return: None
    """

    
    # Initializing masking function for later (may not be necessary)
    masking_func = np.vectorize(lambda x: x != model.padding_index.numpy())
    length = len(os.listdir("data/train"))
    global_max = 0

    # Iterating over all inputs
    for i in range(0, length - model.batch_size.numpy(), model.batch_size.numpy()):
        train_data, batch_max = process(model, i, "data/train")
        global_max = max(global_max, batch_max)
        
        inputs = train_data[:, :-1]
        labels = train_data[:, 1:]

        # Ensuring full batch
        if(len(inputs) == model.batch_size.numpy()):

            # Creating mask
            mask = masking_func(labels)

            # Forward pass
            with tf.GradientTape() as tape:
                probabilities = model(inputs)
                loss = model.loss_function(probabilities, labels, mask)
                print("Training loss is {}".format(loss))

            # Applying gradients
            gradients = tape.gradient(loss, model.trainable_variables)
            model.optimizer.apply_gradients(zip(gradients, model.trainable_variables))
    pass

def process(model, j, folder):
    
    data = get_data_split(folder, j, model.batch_size.numpy())
    # turn the midi files into one-dimensional vectors, with space tokens in between each timestep
    data = format_data(data)

    maximum = np.max(list(map(lambda x: len(x), data)))
    
    data = pad_data(6000, model.padding_index.numpy(), data)
    data = np.asarray(data)
    # slicing data to run on local, using the entire dataset causes memory issues
    data = data[:, :model.window_size.numpy()]
    
    data = np.hstack((data, np.full((data.shape[0], 1), model.space_index.numpy())))
    
    return data, maximum


def test(model):
    """
    Runs through one epoch - all testing examples.

    :param model: the initialized model to use for forward and backward pass
    :param test_data:test data (all data for testing) of shape (num_midis, window_size)
    :returns: a tuple containing at index 0 the perplexity of the test set and at index 1 the per symbol accuracy on test set,
    e.g. (my_perplexity, my_accuracy)
    """

    # Initializing masking function for later
    masking_func = np.vectorize(lambda x: x != model.padding_index.numpy())

    # Initializing iterators
    symbol_count = 0
    plex_sum = 0
    accuracy_sum = 0
    global_max = 0

    length = len(os.listdir("data/test"))

    for i in range(0, length - model.batch_size.numpy(), model.batch_size.numpy()):
        test_data, batch_max = process(model, i, "data/test")
        global_max = max(global_max, batch_max)
        
        inputs = test_data[:, :-1]
        labels = test_data[:, 1:]

        # Ensuring full batch
        if(len(labels) == model.batch_size.numpy()):

            # Counting relevant metrics
            mask = masking_func(labels)
            for i in mask.flatten():
                if i: symbol_count += 1


            probabilities = model(inputs)
            plex_sum += model.loss_function(probabilities, labels, mask)
            accuracy_sum += model.accuracy_function(probabilities, labels, mask)

    # Calculating per symbol accuracy
    perplexity = np.exp(plex_sum / symbol_count)
    accuracy = accuracy_sum / int(len(test_data) / model.batch_size.numpy())

    return (perplexity, accuracy)

def format_data(array):
    for i in range(len(array)):
        midi = array[i]
        index_list = []
        for j in range(len(midi)):
            indices = np.where(midi[j] == 1.0)
            index_list = np.append(index_list, indices)

        array[i] = index_list

    return array

def pad_data(window_size, padding_index, array):
    for i in range(len(array)):
        midi = array[i]
        if len(midi) < window_size:
            missing_steps = window_size - len(midi)
            padding = np.full((missing_steps), padding_index)
            midi = np.append(midi, padding)
            array[i] = midi
    return array

def generate_sequence(model, start_sequence, length):
    padded_sequence = np.asarray(pad_data(model.window_size.numpy(), model.padding_index.numpy(), [start_sequence]))[0]
    # print(padded_sequence.shape)
    final_sequence = start_sequence
    k = 30
    p = 0.80
    count = 0
    seq_index = len(start_sequence)
    # loop until sequence is of the given length
    while len(final_sequence) < model.window_size.numpy() + length:
        # call model on the sequence to get the probability of the next 'word'
        model_input = np.asarray([padded_sequence])
        probs = model(model_input)[0][seq_index]
        # Take the top K elements, and redistribute the probabilities among them (Top K sampling)
        index_array = probs.numpy()
        if padded_sequence[seq_index - 1] == model.space_index.numpy():
            index_array[model.space_index.numpy()] = 0
        index_array = index_array.argsort()[-k:][::-1]
        index_probs = tf.gather(probs, tf.constant(index_array))
        index_probs = tf.nn.softmax(index_probs)

        # Look at the first X words until their probabilites sum up to P (Top P "Nucleus" sampling)
        prob_sum = 0
        indices = []
        i = 0
        while prob_sum < p:
            index = index_array[i]

            prob = index_probs[i]
            prob_sum += prob
            indices.append(index)
            i += 1
        # choose an event randomly from those X words, weighted on their probability.
        next_event = random.choices(indices, index_probs[:i], k=1)[0]
        if next_event == model.space_index.numpy():
            count = 0
        else:
            count += 1

        if count > model.max_phrase_length.numpy():
            next_event = model.space_index.numpy()
            count = np.random.choice(model.phrase_rand_amount.numpy())
        final_sequence.append(next_event)
        if seq_index < model.window_size.numpy() - 1:
            padded_sequence[seq_index] = next_event
            seq_index += 1
        else:
            padded_sequence = np.asarray(final_sequence[-model.window_size.numpy():])



    print("End of generate")
    return final_sequence[model.window_size.numpy():]

def convert_to_vectors(sequence, space_index=412, vector_length=413):
    vectors = []
    vector_indices = []
    # go through each event in the sequence
    for i in range(len(sequence)):
        # append the event to vector_indices
        event = sequence[i]
        vector_indices.append(event)
        # if the event is a space...
        if event == space_index:
            # create a vector for this timestep, filling in all the indices we have so far
            vector = np.zeros(vector_length)
            vector[vector_indices] = 1
            # reset vector_indices
            vector_indices = []
            # append the vector to our vector list
            vectors.append(vector)

    if vector_indices:
        vector = np.zeros(vector_length)
        vector_indices.append(space_index)
        vector[vector_indices] = 1
        vectors.append(vector)


    return np.asarray(vectors)

def singleCall(model):
    masking_func = np.vectorize(lambda x: x != model.padding_index.numpy())
    train_data, batch_max = process(model, 0, "data/train")
    inputs = train_data[:, :-1]
    labels = train_data[:, 1:]
    mask = masking_func(labels)

    # Forward pass
    with tf.GradientTape() as tape:
        probabilities = model(inputs)
        loss = model.loss_function(probabilities, labels, mask)

    # Applying gradients
    gradients = tape.gradient(loss, model.trainable_variables)
    model.optimizer.apply_gradients(zip(gradients, model.trainable_variables))
    pass
    

def main():
    model = Transformer()
    singleCall(model)
    
    #model.load_weights("model_weights")
    
    # Train and Test Model
    if False:
        for i in range(model.num_epochs.numpy()):
            train(model)
            plex, acc = test(model)

            # Printing resulatant perplexity and accuracy
            print("Epoch:", i)
            print("Perplexity", plex, "Accuracy", acc)

    model.save_weights("model_weights")
    # Run model to create mididata
    start_seq = [67, 270, 412]
    # start_seq = [45, 277, 412]
    sequence = np.asarray(generate_sequence(model, start_seq, 4000))
    print(sequence)
    print(sequence[0:300])
    vectors = convert_to_vectors(sequence)

    midi = encoding_to_midi(vectors, "midi_out1.midi")

if __name__ == '__main__':
    main()

