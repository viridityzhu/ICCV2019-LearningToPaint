#!/usr/bin/env python3
import cv2
import random
import numpy as np
import argparse
from DRL.evaluator import Evaluator
from DRL.ddpg import DDPG
from DRL.multi import fastenv
from utils.util import *
from utils.tensorboard import TensorBoard
import time

exp = str(os.path.basename(os.getcwd())) + '_' + str(time.time())
# exp = os.path.abspath('.').split('/')[-1]
writer = TensorBoard('../train_log/{}'.format(exp))
os.system('ln -sf ../train_log/{} ./log'.format(exp))
os.system('mkdir ./model')

def train(agent0, agent1, env0, env1, evaluate):
    train_times = args.train_times
    env_batch = args.env_batch
    validate_interval = args.validate_interval
    max_step = args.max_step
    debug = args.debug
    episode_train_times = args.episode_train_times
    resume = args.resume
    output = args.output
    time_stamp = time.time()
    step = episode = episode_steps = 0
    tot_reward = 0.
    observation_fore = None
    observation_back = None
    noise_factor = args.noise_factor
    while step <= train_times:
        step += 1
        episode_steps += 1
        # reset if it is the start of episode
        if observation_fore is None:
            observation_fore = env0.reset()
            agent0.reset(observation_fore, noise_factor)    
            observation_back = env1.reset()
            agent1.reset(observation_back, noise_factor)

        action = agent0.select_action(observation_fore, episode_steps, noise_factor=noise_factor)
        observation_fore, reward, done, _ = env0.step(action)
        agent0.observe(reward, observation_fore, done, step)
        
        action = agent1.select_action(observation_back, episode_steps, noise_factor=noise_factor)
        observation_back, reward, done, _ = env1.step(action)
        agent1.observe(reward, observation_back, done, step)
        
        if step % 200 == 0:
            print('step: {}, episode: {}, episode_steps: {}, reward: {}'.format(step, episode, episode_steps, reward.mean()))

        # every 40 steps, update policy and reset the environment
        if (episode_steps >= max_step and max_step):
            if step > args.warmup:
                # [optional] evaluate
                if episode > 0 and validate_interval > 0 and episode % validate_interval == 0:
                    reward0, dist0 = evaluate(env0, agent0.select_action, agent_num=0, debug=debug)
                    if debug: prRed('Step_{:07d}: mean_reward0:{:.3f} mean_dist0:{:.3f} var_dist0:{:.3f}'.format(step - 1, np.mean(reward0), np.mean(dist0), np.var(dist0)))
                    writer.add_scalar('validate/mean_reward0', np.mean(reward0), step)
                    writer.add_scalar('validate/mean_dist0', np.mean(dist0), step)
                    writer.add_scalar('validate/var_dist0', np.var(dist0), step)
                    agent0.save_model(output, 0)
                    
                    reward1, dist1 = evaluate(env1, agent1.select_action, agent_num=1, debug=debug)
                    if debug: prRed('Step_{:07d}: mean_reward1:{:.3f} mean_dist1:{:.3f} var_dist1:{:.3f}'.format(step - 1, np.mean(reward1), np.mean(dist1), np.var(dist1)))
                    writer.add_scalar('validate/mean_reward1', np.mean(reward1), step)
                    writer.add_scalar('validate/mean_dist1', np.mean(dist1), step)
                    writer.add_scalar('validate/var_dist1', np.var(dist1), step)
                    agent1.save_model(output, 1)

            train_time_interval = time.time() - time_stamp
            time_stamp = time.time()
            tot_Q0 = 0.
            tot_Q1 = 0.
            tot_value_loss0 = 0.
            tot_value_loss1 = 0.
            if step > args.warmup:
                # adjust learning rate
                if step < 10000 * max_step:
                    lr = (3e-4, 1e-3) # lr for critic, lr for actor
                elif step < 20000 * max_step:
                    lr = (1e-4, 3e-4)
                else:
                    lr = (3e-5, 1e-4)
                # update policy
                for i in range(episode_train_times):
                    Q0, value_loss0 = agent0.update_policy(lr)
                    tot_Q0 += Q0.data.cpu().numpy()
                    tot_value_loss0 += value_loss0.data.cpu().numpy()
                    
                    Q1, value_loss1 = agent1.update_policy(lr)
                    tot_Q1 += Q1.data.cpu().numpy()
                    tot_value_loss1 += value_loss1.data.cpu().numpy()
                writer.add_scalar('train/critic_lr', lr[0], step)
                writer.add_scalar('train/actor_lr', lr[1], step)
                writer.add_scalar('train/Q0', tot_Q0 / episode_train_times, step)
                writer.add_scalar('train/Q1', tot_Q1 / episode_train_times, step)
                writer.add_scalar('train/critic_loss0', tot_value_loss0 / episode_train_times, step)
                writer.add_scalar('train/critic_loss1', tot_value_loss1 / episode_train_times, step)
            if debug: prBlack('#{}: steps:{} interval_time:{:.2f} train_time:{:.2f}' \
                .format(episode, step, train_time_interval, time.time()-time_stamp)) 
            time_stamp = time.time()
            # reset
            observation_fore = None
            observation_back = None
            episode_steps = 0
            episode += 1
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Learning to Paint')

    # hyper-parameter
    parser.add_argument('--warmup', default=400, type=int, help='timestep without training but only filling the replay memory')
    parser.add_argument('--discount', default=0.95**5, type=float, help='discount factor')
    parser.add_argument('--batch_size', default=96, type=int, help='minibatch size')
    parser.add_argument('--rmsize', default=800, type=int, help='replay memory size')
    parser.add_argument('--env_batch', default=96, type=int, help='concurrent environment number')
    parser.add_argument('--tau', default=0.001, type=float, help='moving average for target network')
    parser.add_argument('--max_step', default=40, type=int, help='max length for episode')
    parser.add_argument('--noise_factor', default=0, type=float, help='noise level for parameter space noise')
    parser.add_argument('--validate_interval', default=50, type=int, help='how many episodes to perform a validation')
    parser.add_argument('--validate_episodes', default=1, type=int, help='how many episode to perform during validation') # 5
    parser.add_argument('--train_times', default=2000000, type=int, help='total traintimes')
    parser.add_argument('--episode_train_times', default=10, type=int, help='train times for each episode')    
    parser.add_argument('--resume', default=None, type=str, help='Resuming model path for testing')
    parser.add_argument('--output', default='./model', type=str, help='Resuming model path for testing')
    parser.add_argument('--debug', dest='debug', action='store_true', help='print some info')
    parser.add_argument('--seed', default=1234, type=int, help='random seed')
    
    args = parser.parse_args()    
    args.output = get_output_folder(args.output, "Paint")
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(args.seed)
    random.seed(args.seed)
    torch.backends.cudnn.deterministic = False
    torch.backends.cudnn.benchmark = True
    from DRL.ddpg import DDPG
    from DRL.multi import fastenv
    fenv = fastenv(args.max_step, args.env_batch, 0, writer)
    agent = DDPG(args.batch_size, args.env_batch, args.max_step, \
                 args.tau, args.discount, args.rmsize, \
                 writer, args.resume, args.output)
    fenv1 = fastenv(args.max_step, args.env_batch, 1, writer)
    agent1 = DDPG(args.batch_size, args.env_batch, args.max_step, \
                 args.tau, args.discount, args.rmsize, \
                 writer, args.resume, args.output)
    evaluate = Evaluator(args, writer)
    print('observation_space', fenv.observation_space, 'action_space', fenv.action_space)
    train(agent, agent1, fenv, fenv1, evaluate)
