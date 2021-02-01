import time
import gym
from gym.utils import seeding
import numpy as np
import pygame

from scipy.spatial.transform import Rotation as R

X = 1
Y = 0

class WorldMap():
    def __init__(self, dim, n_agents):
        self.dim = dim
        self.map_grid_shape = (200, 200)
        self.n_agents = n_agents
        self.map = np.zeros((self.map_grid_shape[Y], self.map_grid_shape[X], 1+self.n_agents), dtype=np.bool)
        self.map[:85, 98:102, 0] = True
        self.map[115:, 98:102, 0] = True
        
        yy, xx = np.mgrid[:self.map_grid_shape[Y], :self.map_grid_shape[X]]
        self.yy = (yy/self.map_grid_shape[Y])*dim[Y]
        self.xx = (xx/self.map_grid_shape[X])*dim[X]

    def set_robot(self, position, agent_idx):
        rob_map = np.zeros(self.map_grid_shape, dtype=np.bool)
        sel = (((self.yy - position[Y]) ** 2 + (self.xx - position[X]) ** 2) < 0.1**2)
        rob_map[sel] = True

        if self.is_colliding_wall(rob_map):
            return "wall"

        if self.is_colliding_other_agent(agent_idx, rob_map):
            return "agent"

        self.map[:,:,agent_idx+1] = rob_map
        return "ok"

    def is_colliding_wall(self, m):
        return np.any(m & self.map[:,:,0])

    def is_colliding_other_agent(self, agent_idx, m):
        for other_agent_idx in range(self.n_agents):
            if other_agent_idx == agent_idx:
                continue
            if np.any(m & self.map[:,:,other_agent_idx+1]):
                return True
        return False

    def render(self):
        m_acc = np.zeros(self.map_grid_shape, dtype=np.bool)
        for i in range(self.map.shape[2]):
            m_acc = m_acc | self.map[:,:,i]
        return ~m_acc

class Turtlebot():
    CONFIG = {
        'limits': {
            'forward_speed': (-0.2, 0.2),
            'yaw_rate': (-np.pi/8, np.pi/8),
            'vx': (-1, 1),
            'vy': (-1, 1),
        },
    }

    def __init__(self, index, world_map):
        self.index = index
        self.world_map = world_map

        self.reset(np.array([0, 0]), np.array([0, 0]))

    def reset(self, start_pos, goal_pos):
        #self.orientation = R.from_euler("z", 90, degrees=True)
        self.position = start_pos.copy()
        self.goal_pos = goal_pos.copy()

        self.setpoint_forward_speed = 0
        self.setpoint_yaw_rate = 0
        self.vx = 0
        self.vy = 0
        self.reached_goal = False

    def set_world_velocity(self, vx, vy):
        #if angular > 0 and lateral > 0:
        #if np.isnan(angular) or np.isnan(lateral):
        #import pdb; pdb.set_trace()
        #assert not np.isnan(angular)
        #assert not np.isnan(lateral)
        self.vx = np.clip(vx, *self.CONFIG['limits']['vx'])
        self.vy = np.clip(vy, *self.CONFIG['limits']['vy'])

    def set_velocity(self, angular, lateral):
        #if angular > 0 and lateral > 0:
        if np.isnan(angular) or np.isnan(lateral):
            import pdb; pdb.set_trace()
        #assert not np.isnan(angular)
        #assert not np.isnan(lateral)
        self.setpoint_forward_speed = np.clip(lateral, *self.CONFIG['limits']['forward_speed'])
        self.setpoint_yaw_rate = np.clip(angular, *self.CONFIG['limits']['yaw_rate'])

    def get_rotation_matrix(self):
        return self.orientation.as_matrix()

    def step(self):
        dt=0.1
        new_pos = self.position + np.array([self.vx, self.vy])*dt
        pos_map_status = self.world_map.set_robot(new_pos, self.index)

        if pos_map_status == "ok":
            self.position = np.clip(new_pos, [0, 0], self.world_map.dim)
        #self.position += self.orientation.apply(np.array([self.setpoint_forward_speed, 0, 0]) * dt)
        #self.orientation *= R.from_euler("xyz", np.array([0, 0, -self.setpoint_yaw_rate]) * dt)

        obs = np.hstack([self.position, self.goal_pos - self.position])
             
        return obs, pos_map_status

class SimpleEnv(gym.Env):
    def __init__(self, config):
        self.seed(0)

        self.cfg = config
        n_agents = len(self.cfg['agent_formation'])
        self.action_space = gym.spaces.Tuple(
            (gym.spaces.Box(low=-np.inf, high=np.inf, shape=(2,), dtype=float),)*n_agents) # velocity yaw and forward

        self.observation_space = gym.spaces.Dict({
            # current pose relative to goal (x,y)
            # current pose relative to origin (and therefore gap in wall) (x, y, phi)
            # current velocity (lin, ang)
            'agents': gym.spaces.Tuple((
                gym.spaces.Dict({
                    "obs": gym.spaces.Box(-10000, 10000, shape=(4,), dtype=float),
                    #"img": gym.spaces.Box(0, 1, shape=(20, 30, 2), dtype=int),
                    #"state": gym.spaces.Box(low=-10000, high=10000, shape=(6,))
                })
            ,)*n_agents),
            'gso': gym.spaces.Box(-1, 1, shape=(n_agents, n_agents), dtype=float),
        })

        self.map = WorldMap(self.cfg['world_shape'], len(self.cfg['agent_formation']))
    
        self.robots = []
        for i in range(len(self.cfg['agent_formation'])):
            self.robots.append(Turtlebot(i, self.map))

        self.display = None
        self.render_frame_index = 0

        self.reset()

    def seed(self, seed=None):
        self.random_state, seed = seeding.np_random(seed)
        return [seed]

    def reset(self):
        self.timestep = 0
        
        theta = self.random_state.uniform(-np.pi / 4, np.pi / 4)
        c, s = np.cos(theta), np.sin(theta)
        R = np.array(((c, -s), (s, c)))
        rotated_formation = np.dot(self.cfg['agent_formation'], R)

        offset_start = self.random_state.uniform([0.5, 0.5], [2.5, 0.8])
        offset_goal = self.random_state.uniform([0.5, 2], [2.5, 2.5])

        starts = rotated_formation + offset_start
        goals = rotated_formation + offset_goal
        
        for robot, start, goal in zip(self.robots, starts, goals):
            robot.reset(start, goal)
        return self.step([[0, 0]]*len(self.robots))[0]

    def compute_gso(self):
        dists = np.zeros((len(self.robots), len(self.robots)))
        for agent_y in range(len(self.robots)):
            for agent_x in range(len(self.robots)):
                dst = np.sum(np.array(self.robots[agent_x].position - self.robots[agent_y].position)**2)
                dists[agent_y, agent_x] = dst
                dists[agent_x, agent_y] = dst

        A = dists < (self.cfg['communication_range']**2)
        np.fill_diagonal(A, 0)
        return A.astype(np.float)

    def step(self, actions):
        self.timestep += 1
        obs, infos = [], {'rewards': {}}
        reward = 0

        world_done = self.timestep > self.cfg['max_time_steps']
        for i, (robot, action) in enumerate(zip(self.robots, actions)):
            robot.set_world_velocity(action[0], action[1])
            o, pos_map_status = robot.step()
            
            goal_vector = robot.goal_pos - robot.position
            world_speed = np.array([robot.vx, robot.vy])
            r = 0
            #if np.linalg.norm(np.array([1.5,1.5]) - robot.position, ord=2) < 0.01 and not robot.reached_goal:
            #    r += 50
            #    robot.reached_goal = True
            vw = np.linalg.norm(world_speed)
            if vw > 0:
                #if robot.position[1] > 1.5:
                #goal_vector = robot.goal_pos - robot.position
                #else:
                #    goal_vector = np.array([1.5, 1.5]) - robot.position
                r = np.dot(goal_vector/np.linalg.norm(goal_vector), world_speed/vw)*vw
            reached_goal = np.linalg.norm(goal_vector, ord=2) < 0.1
            if reached_goal:
                if not robot.reached_goal:
                    r = 500
                    robot.reached_goal = True
                else:
                    r = 0
            if pos_map_status == "wall":
                world_done = True
                r -= 10
            #r -= 1 # incentivize speed
            #elif pos_map_status == "agent":
            #    r -= 10

            obs.append({'obs': o})
            infos['rewards'][i] = r
            reward += r

        #state = []
        #for r, o in zip(self.robots, obs):
        #    state.append(np.concatenate([o, np.array(r.position)]))
        obs = {
            'agents': tuple(obs),
            'gso': self.compute_gso(),
            #'state': np.array(state)
        }
        #if not np.all(np.isfinite(obs['state'])) or not np.all(np.isfinite(obs['gso'])):
        #     import pdb; pdb.set_trace()

        #print(self.timestep)
        world_done = world_done or all([robot.reached_goal for robot in self.robots])
        #print("INF", actions, infos, len(self.robots))
        return obs, reward, world_done, infos

    def clear_patches(self, ax):
        [p.remove() for p in reversed(ax.patches)]
        [t.remove() for t in reversed(ax.texts)]

    def render(self):
        if self.display is None:
            pygame.init()
            self.display = pygame.display.set_mode((200,200))
        surf = pygame.surfarray.make_surface(self.map.render().astype(np.uint8)*255)
        self.display.blit(surf, (0, 0))
        for robot in self.robots:
            pygame.draw.line(self.display, (0,0,255), robot.position/self.map.dim*[200,200], robot.goal_pos/self.map.dim*[200,200], 2)
        if True:
            self.render_frame_index += 1
            pygame.image.save(self.display, f"./img/{self.render_frame_index}.png")
        pygame.display.update()

