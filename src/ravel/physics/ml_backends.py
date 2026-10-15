"""Small deterministic training backends; no dynamic source execution.

Extensions implement fit/predict using only train arrays. Test arrays are owned
by the executor and never passed to fit. NumPy is the reference CPU backend.
"""
from importlib.util import find_spec
import numpy as np

FAMILIES = {'numpy': {'logistic', 'mlp'}, 'sklearn': {'logistic'},
            'torch': {'logistic', 'mlp'}, 'torch-geometric': {'gnn'}}
PACKAGES = {'numpy': 'numpy', 'sklearn': 'sklearn', 'torch': 'torch', 'torch-geometric': 'torch_geometric'}


def available():
    result = {name: find_spec(package) is not None for name, package in PACKAGES.items()}
    result['torch-geometric'] = result['torch-geometric'] and result['torch']
    return result


def sigmoid(x):
    return 1. / (1. + np.exp(-np.clip(x, -40, 40)))


def fit(arm, x, y, weights, seed, epochs, check_deadline):
    backend = arm['backend']
    if backend not in FAMILIES or arm['architecture'] not in FAMILIES[backend]:
        raise ValueError('unsupported training backend or model family')
    if not available()[backend]:
        raise ValueError(f'training backend {backend} is not installed')
    if backend == 'torch-geometric':
        return _fit_graph(arm, x, y, weights, seed, epochs, check_deadline)
    x = x.reshape(len(x), -1)
    config = arm['config']; rate = config['learning_rate']
    width = config.get('hidden_units', 8)
    rng = np.random.default_rng(seed)
    mean = np.average(x, axis=0, weights=weights)
    scale = np.sqrt(np.average((x-mean)**2, axis=0, weights=weights))
    scale = np.where(scale > 1.e-12, scale, 1.)
    z = (x-mean)/scale
    if backend == 'sklearn':
        # SGDClassifier supports sample weights and one fixed full epoch per call.
        # sklearn MLP sample-weight support varies by version; refuse that arm.
        if arm['architecture'] != 'logistic':
            raise ValueError('sklearn backend currently supports weighted logistic only; use numpy or torch MLP')
        from sklearn.linear_model import SGDClassifier
        model = SGDClassifier(loss='log_loss', learning_rate='constant', eta0=rate,
                              alpha=0, random_state=seed, shuffle=False)
        for _ in range(epochs):
            check_deadline(); model.partial_fit(z, y, classes=np.array([0, 1]), sample_weight=weights)
        return {'mean': mean, 'scale': scale, 'w': model.coef_[0], 'b': model.intercept_}
    if backend == 'torch':
        import torch
        # Local generator and explicit tensor operations avoid changing global RNG.
        gen = torch.Generator(device='cpu').manual_seed(seed)
        tx = torch.tensor(z, dtype=torch.float64)
        ty = torch.tensor(y, dtype=torch.float64)
        tw = torch.tensor(weights/weights.sum(), dtype=torch.float64)
        w = torch.randn((z.shape[1], width) if arm['architecture']=='mlp' else (z.shape[1],),
                        generator=gen, dtype=torch.float64) / np.sqrt(z.shape[1])
        b = torch.zeros(width if arm['architecture']=='mlp' else 1, dtype=torch.float64)
        params = [w.requires_grad_(), b.requires_grad_()]
        if arm['architecture']=='mlp':
            v = (torch.randn(width, generator=gen, dtype=torch.float64)/np.sqrt(width)).requires_grad_()
            c = torch.zeros(1, dtype=torch.float64, requires_grad=True); params += [v, c]
        for _ in range(epochs):
            check_deadline()
            logits = tx@w+b if len(params)==2 else torch.tanh(tx@w+b)@v+c
            loss = (torch.nn.functional.binary_cross_entropy_with_logits(logits, ty, reduction='none')*tw).sum()
            loss.backward()
            with torch.no_grad():
                for p in params: p -= rate*p.grad; p.grad.zero_()
        state = dict(zip(('w','b','v','c'), [p.detach().numpy() for p in params]))
        return {'mean': mean, 'scale': scale, **state}
    state = {'mean': mean, 'scale': scale}
    if arm['architecture'] == 'logistic':
        w = rng.normal(0, .01, size=z.shape[1]); b = np.zeros(1)
        for _ in range(epochs):
            check_deadline()
            residual = (sigmoid(z@w+b)-y)*weights/weights.sum()
            w -= rate*(z.T@residual); b -= rate*residual.sum()
        state.update(w=w, b=b)
    else:
        w = rng.normal(size=(z.shape[1], width))/np.sqrt(z.shape[1]); b = np.zeros(width)
        v = rng.normal(size=width)/np.sqrt(width); c = np.zeros(1)
        for _ in range(epochs):
            check_deadline()
            hidden = np.tanh(z@w+b)
            residual = (sigmoid(hidden@v+c)-y)*weights/weights.sum()
            dh = residual[:, None]*v[None, :]*(1-hidden**2)
            dw, db, dv, dc = z.T@dh, dh.sum(axis=0), hidden.T@residual, residual.sum()
            w -= rate*dw; b -= rate*db; v -= rate*dv; c -= rate*dc
        state.update(w=w, b=b, v=v, c=c)
    return state


def predict(state, x):
    if 'cut_feature' in state:
        values=x[:, int(state['cut_feature'])]
        return (values >= state['cut_threshold'] if state['cut_above'] else values <= state['cut_threshold']).astype(float)
    if 'graph_nodes' in state:
        return _predict_graph(state, x)
    x = x.reshape(len(x), -1)
    z = (x-state['mean'])/state['scale']
    logits = z@state['w']+state['b']
    if 'v' in state: logits = np.tanh(logits)@state['v']+state['c']
    result = sigmoid(logits)
    if not np.all(np.isfinite(result)): raise ValueError('nonfinite predictions')
    return result


def _graph_model(features, hidden):
    """Fixed-topology GCN and mean pooling; caller supplies every graph edge."""
    import torch
    from torch_geometric.nn import GCNConv, global_mean_pool

    class GraphClassifier(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.conv = GCNConv(features, hidden, add_self_loops=True, normalize=True)
            self.head = torch.nn.Linear(hidden, 1)

        def forward(self, nodes, edges, batch):
            hidden_nodes = torch.tanh(self.conv(nodes, edges))
            return self.head(global_mean_pool(hidden_nodes, batch)).reshape(-1)

    return GraphClassifier().double()


def _graph_batch(x, mean, scale, edge_index):
    import torch
    events, nodes, features = x.shape
    z = ((x-mean)/scale).reshape(events*nodes, features)
    edge = torch.tensor(edge_index, dtype=torch.long)
    edges = torch.cat([edge+i*nodes for i in range(events)], dim=1)
    batch = torch.arange(events, dtype=torch.long).repeat_interleave(nodes)
    return torch.tensor(z, dtype=torch.float64), edges, batch


def _fit_graph(arm, x, y, weights, seed, epochs, check_deadline):
    import torch
    config = arm['config']
    mean = np.average(x.mean(axis=1), axis=0, weights=weights)
    scale = np.sqrt(np.average(((x-mean)**2).mean(axis=1), axis=0, weights=weights))
    scale = np.where(scale > 1.e-12, scale, 1.)
    # Constructors consume the global torch RNG; restore it at context exit.
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(seed)
        model = _graph_model(x.shape[-1], config['hidden_units'])
        batch = _graph_batch(x, mean, scale, config['edge_index'])
        labels = torch.tensor(y, dtype=torch.float64)
        w = torch.tensor(weights/weights.sum(), dtype=torch.float64)
        optimizer = torch.optim.SGD(model.parameters(), lr=config['learning_rate'])
        for _ in range(epochs):
            check_deadline(); optimizer.zero_grad()
            loss = (torch.nn.functional.binary_cross_entropy_with_logits(
                model(*batch), labels, reduction='none')*w).sum()
            loss.backward(); optimizer.step()
        state = {'parameter:'+k: v.detach().cpu().numpy() for k, v in model.state_dict().items()}
    return {**state, 'mean':mean, 'scale':scale, 'graph_nodes':np.array(config['nodes']),
            'graph_features':np.array(x.shape[-1]), 'graph_hidden':np.array(config['hidden_units']),
            'edge_index':np.array(config['edge_index'], dtype=np.int64)}


def _predict_graph(state, x):
    import torch
    if x.ndim!=3 or x.shape[1:]!=(int(state['graph_nodes']),int(state['graph_features'])):
        raise ValueError('graph prediction shape changed')
    with torch.random.fork_rng(devices=[]):
        model = _graph_model(int(state['graph_features']),int(state['graph_hidden']))
        model.load_state_dict({k.removeprefix('parameter:'):torch.tensor(v)
                               for k,v in state.items() if k.startswith('parameter:')})
        model.eval()
        with torch.no_grad():
            score = torch.sigmoid(model(*_graph_batch(x,state['mean'],state['scale'],state['edge_index']))).numpy()
    if not np.all(np.isfinite(score)): raise ValueError('nonfinite graph predictions')
    return score


def _design(x, architecture):
    if architecture != 'quadratic_logistic':
        return x
    return np.column_stack([x] + [(x[:,i]*x[:,j])[:,None]
                                  for i in range(x.shape[1]) for j in range(i,x.shape[1])])


def _forward(state, x):
    z = _design(x, str(state['architecture']))
    activations = [z]
    for i in range(int(state['layers'])):
        logits = z @ state[f'w{i}'] + state[f'b{i}']
        z = np.maximum(logits,0) if i < int(state['layers'])-1 else sigmoid(logits)
        activations.append(z)
    return activations


def predict_selected(state, x):
    result = _forward(state, x)[-1].reshape(-1)
    if not np.all(np.isfinite(result)): raise ValueError('nonfinite selected model prediction')
    return result


def fit_selected(arm, train, val, seed, budget, check_deadline):
    """NumPy ReLU layers, sigmoid head; selection and stopping use validation only.

    Returns the best checkpoint and every executed epoch's weighted BCE. Epoch
    and wall fields are ceilings shared by arms, not promises of equal FLOPs.
    """
    rng=np.random.default_rng(seed)
    dim=_design(train['x'], arm['architecture']).shape[1]
    widths=[dim]+(arm['config']['widths'] if arm['architecture']=='mlp' else [])+[1]
    if len(train['x'])*max(widths)>4_000_000: raise ValueError('hidden expansion exceeds memory bound')
    state={'architecture':np.array(arm['architecture']), 'layers':np.array(len(widths)-1)}
    for i,(a,b) in enumerate(zip(widths,widths[1:])):
        state[f'w{i}']=rng.normal(size=(a,b))*np.sqrt(2/a)
        state[f'b{i}']=np.zeros(b)
    rate=arm['config']['learning_rate']; best_loss=float('inf'); stale=0; best=None; history=[]
    def loss(batch):
        p=np.clip(predict_selected(state,batch['x']),1.e-12,1-1.e-12)
        return float(np.average(-batch['y']*np.log(p)-(1-batch['y'])*np.log1p(-p),weights=batch['weight']))
    for epoch in range(budget['epochs']):
        check_deadline()
        acts=_forward(state,train['x'])
        delta=(acts[-1].reshape(-1)-train['y'])*train['weight']/train['weight'].sum()
        delta=delta[:,None]; grads={}
        for i in reversed(range(len(widths)-1)):
            grads[f'w{i}']=acts[i].T@delta; grads[f'b{i}']=delta.sum(axis=0)
            if i:
                delta=(delta@state[f'w{i}'].T)*(acts[i]>0)
        for name,value in grads.items(): state[name] -= rate*value
        training,validation=loss(train),loss(val)
        if not np.isfinite(training+validation): raise ValueError('nonfinite training loss')
        history.append({'epoch':epoch+1,'training_loss':training,'validation_loss':validation})
        if validation < best_loss:
            best_loss=validation; best={k:v.copy() for k,v in state.items()}; stale=0
        else:
            stale+=1
            if stale>=budget['patience']: break
    check_deadline()
    return best, history, best_loss


from .ml_runtime import bind
bind(globals())
