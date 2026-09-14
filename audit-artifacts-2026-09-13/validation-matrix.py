import copy,json,pathlib,time
from vendoo_studio.models.validation import validate_listing
root=pathlib.Path(__file__).parent
base=json.loads((root/'approved-studio-snapshot.json').read_text())['listing']
cases=[]
def add(name,path=None,value=None,delete=False,photos=5):
 d=copy.deepcopy(base)
 if path:
  parts=path.split('.')
  cur=d
  for k in parts[:-1]:cur=cur.setdefault(k,{})
  if delete:cur.pop(parts[-1],None)
  else:cur[parts[-1]]=value
 t=time.monotonic()
 try:
  r=validate_listing(d,photos);out={'can_send':r.can_send,**r.model_dump()}
 except Exception as e:out={'exception':type(e).__name__+': '+str(e)}
 cases.append({'case':name,'path':path,'test_value':value,'deleted':delete,'photo_count':photos,'duration':time.monotonic()-t,**out})
add('baseline')
for field in ['title','description','price','brand','size','sku','weight_lb','weight_oz']:
 add('missing '+field,field,delete=True)
for name,path,value in [
 ('blank title','title','   '),('empty title','title',''),('overlong title','title','A'*81),('wrong title formula','title','Nice blouse'),
 ('wrong description','description','Nice blouse'),('zero price','price',0),('negative price','price',-1),('invalid package','package_dimensions_in','banana'),
 ('nonterminal category','category_path','Clothing'),('department mismatch','department','Men'),('size mismatch','ebay_specifics.size','S'),
 ('missing ebay specifics','ebay_specifics',{}),('wrong ebay keys','ebay_specifics',{'Size':'XL','Department':'Women'}),('invalid season','ebay_specifics.season','Moon season'),
 ('invalid Depop source','depop_specifics.source','Invented'),('invalid Depop age','depop_specifics.age','Invented'),('invalid Depop style','depop_specifics.style',['Invented']),
 ('four Depop styles','depop_specifics.style',['Casual','Retro','Minimalist','Preppy']),('invalid material','depop_specifics.material','Invented'),
 ('invalid occasion','depop_specifics.occasion',['Invented']),('invalid parcel','depop_specifics.parcelSize','Truck'),('regular grouping','depop_specifics.sizeGrouping','Regular'),
 ('invalid Etsy who','etsy_specifics.who_made','Invented'),('invalid Etsy what','etsy_specifics.what_is','Invented'),('invalid Etsy when','etsy_specifics.when_made','Invented'),
 ('ineligible modern Etsy','etsy_specifics.when_made','2020 - 2026'),('unsupported care','ebay_specifics.garmentCare','Machine Washable'),('unsupported composition','ebay_specifics.material','100% Silk'),
 ('14 Etsy tags','etsy_specifics.tags',[str(i) for i in range(14)]),('11 Etsy materials','etsy_specifics.materials',[str(i) for i in range(11)]),
 ('boolean false','audit_false',False),('numeric zero','audit_zero',0),('unknown nested','audit_extra',{'array':['one','two'],'empty':'','null':None}),
 ('invalid ebay object type','ebay_specifics','invalid'),('invalid depop object type','depop_specifics','invalid')]:add(name,path,value)
add('missing photos',photos=0)
add('missing material evidence','ebay_specifics.material','')
(root/'validation-matrix.json').write_text(json.dumps(cases,indent=2))
for c in cases:print(c['case'],c.get('can_send'),len(c.get('errors',[])),len(c.get('warnings',[])),c.get('exception',''))
print('cases',len(cases),'accepted',sum(c.get('can_send',False) for c in cases),'exceptions',sum('exception'in c for c in cases))
