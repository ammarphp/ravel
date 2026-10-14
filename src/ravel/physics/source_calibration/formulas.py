"""Tiny non-executing AST evaluator for retained zero-parameter source TF1s."""
import ast,math

def evaluate_tf1(function,x):
 if type(x) not in (int,float) or not math.isfinite(x) or any(type(function[k]) is not int for k in ['npar','ndim','type']) or function['npar']!=0 or function['ndim']!=1 or function['type']!=0:
  raise ValueError('Only finite x and explicit one-dimensional zero-parameter formula TF1 supported')
 if ''.join(function['formula'].split())!=''.join(function['title'].split()) or function['parameters']:
  raise ValueError('Active TF1 expression differs from checked formula/title/parameter contract')
 tree=ast.parse(function['formula'],mode='eval')
 if sum(1 for _ in ast.walk(tree))>64:raise ValueError('Bounded source formula required')
 def evaluate(node):
  if isinstance(node,ast.Expression):return evaluate(node.body)
  if isinstance(node,ast.Constant) and type(node.value) in (int,float):return node.value
  if isinstance(node,ast.Name) and node.id=='x':return x
  if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.USub,ast.UAdd)):
   v=evaluate(node.operand);return -v if isinstance(node.op,ast.USub) else v
  if isinstance(node,ast.BinOp):
   a,b=evaluate(node.left),evaluate(node.right)
   if isinstance(node.op,ast.Mult):return a*b
   if isinstance(node.op,ast.Add):return a+b
   if isinstance(node.op,ast.Sub):return a-b
  if isinstance(node,ast.Compare) and len(node.ops)==1 and isinstance(node.ops[0],ast.GtE):return float(evaluate(node.left)>=evaluate(node.comparators[0]))
  raise ValueError('Unsupported source formula node; never execute arbitrary ROOT titles')
 out=float(evaluate(tree))
 if not math.isfinite(out):raise ValueError('Nonfinite source formula value')
 return out
